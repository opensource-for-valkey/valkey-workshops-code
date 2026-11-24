"""Client configuration and Sentinel recovery without contacting a server."""

from collections import defaultdict, deque
import os
from pathlib import Path
import sys

import pytest
from glide_sync import (
    ConnectionError,
    GlideClientConfiguration,
    GlideClusterClientConfiguration,
    NodeDiscoveryMode,
    ProtocolVersion,
    RequestError,
    TimeoutError,
)

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB))
import valkey_client as manager  # noqa: E402


def relevant(name):
    return name.startswith("VALKEY_") or name == "WORKSHOP_ENV_FILE"


@pytest.fixture
def settings(tmp_path):
    """Keep both process configuration and dotenv loading isolated per test."""
    original = {name: value for name, value in os.environ.items() if relevant(name)}
    for name in list(os.environ):
        if relevant(name):
            del os.environ[name]
    env_file = tmp_path / ".env"
    env_file.write_text("VALKEY_PASSWORD=unit-test-password\n")
    os.environ["VALKEY_ENV_FILE"] = str(env_file)
    try:
        yield env_file
    finally:
        for name in list(os.environ):
            if relevant(name):
                del os.environ[name]
        os.environ.update(original)


def configure_env(**values):
    os.environ.update({name: str(value) for name, value in values.items()})


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds=1.01):
        self.now += seconds

    def sleep(self, seconds):
        self.now += seconds


class FakeConnection:
    def __init__(self, network, config, *, monitor=False):
        self.network = network
        self.config = config
        self.monitor = monitor
        self.host = config.addresses[0].host
        self.calls = []
        self.close_count = 0

    def close(self):
        self.close_count += 1

    def custom_command(self, arguments, *args, **kwargs):
        self.calls.append(("custom_command", list(arguments), args, kwargs))
        command = str(arguments[0]).upper()
        if self.monitor:
            assert command == "SENTINEL"
            assert arguments[1].lower() == "get-master-addr-by-name"
            assert arguments[2] == "workshop"
            result = self.network.monitor_responses.get(self.host, self.network.primary)
            if isinstance(result, BaseException):
                raise result
            return [result[0].encode(), str(result[1]).encode()] if result else None
        if command == "ROLE":
            return [self.network.roles.get(self.host, b"master"), 0, []]
        return self.network.run(self, "custom_command", arguments, kwargs)

    def try_get_pubsub_message(self):
        self.calls.append(("try_get_pubsub_message", (), (), {}))
        if self.network.poll_hook is not None:
            self.network.poll_hook(self)
        messages = self.network.messages[self.host]
        return messages.popleft() if messages else None

    def __getattr__(self, name):
        def command(*args, **kwargs):
            self.calls.append((name, args, (), kwargs))
            return self.network.run(self, name, args, kwargs)

        return command


class FakeNetwork:
    def __init__(self):
        self.primary = ("data-one", 6379)
        self.monitor_responses = {}
        self.roles = {}
        self.creation_errors = {}
        self.command_errors = {}
        self.on_command_error = None
        self.poll_hook = None
        self.messages = defaultdict(deque)
        self.created = []
        self.factory_calls = []

    def create(self, config):
        self.factory_calls.append(config)
        host = config.addresses[0].host
        if host in self.creation_errors:
            raise self.creation_errors[host]
        connection = FakeConnection(self, config, monitor=host.startswith("sentinel-"))
        self.created.append(connection)
        return connection

    def run(self, connection, name, args, kwargs):
        error = self.command_errors.pop((connection.host, name), None)
        if error is not None:
            if self.on_command_error is not None:
                self.on_command_error()
            raise error
        if name == "get":
            return connection.host.encode()
        return b"OK"

    @property
    def data_connections(self):
        return [connection for connection in self.created if not connection.monitor]

    @property
    def monitor_connections(self):
        return [connection for connection in self.created if connection.monitor]


@pytest.fixture
def network(monkeypatch, settings):
    fake = FakeNetwork()
    monkeypatch.setattr(manager.GlideClient, "create", fake.create)
    monkeypatch.setattr(manager.GlideClusterClient, "create", fake.create)
    return fake


@pytest.fixture
def clock(monkeypatch):
    fake = Clock()
    monkeypatch.setattr(manager.time, "monotonic", fake)
    monkeypatch.setattr(manager.time, "sleep", fake.sleep)
    return fake


def sentinel_settings(**extra):
    configure_env(
        VALKEY_MODE="sentinel",
        VALKEY_SENTINEL_NODES="sentinel-one:26379,sentinel-two:26379",
        VALKEY_SENTINEL_SERVICE="workshop",
        **extra,
    )


@pytest.mark.parametrize("mode", ["standalone", "cluster"])
def test_native_factory_configuration_and_lifetime(network, mode):
    configure_env(
        VALKEY_MODE=mode,
        VALKEY_NODES="data-one:6380,data-two:6382",
        VALKEY_USERNAME="workshop-user",
        VALKEY_REQUEST_TIMEOUT_MS=4567,
        VALKEY_CONNECTION_TIMEOUT_MS=2345,
        VALKEY_CLIENT_NAME="unit-client",
    )
    owner = manager.ValkeyClientManager()
    with owner as client:
        assert client is network.data_connections[0]
        assert owner.client is client
        config = client.config
        expected = GlideClusterClientConfiguration if mode == "cluster" else GlideClientConfiguration
        assert isinstance(config, expected)
        assert [(node.host, node.port) for node in config.addresses] == [
            ("data-one", 6380), ("data-two", 6382)
        ]
        assert config.credentials.username == "workshop-user"
        assert config.credentials.password == "unit-test-password"
        assert config.request_timeout == 4567
        assert config.advanced_config.connection_timeout == 2345
        assert config.client_name == "unit-client"
        assert config.database_id == 0
        assert config.use_tls is False
    assert client.close_count == 1
    assert owner.client is None


def test_standalone_host_port_and_process_override_dotenv(network, settings):
    settings.write_text("VALKEY_PASSWORD=dotenv-password\nVALKEY_HOST=dotenv-host\n")
    configure_env(VALKEY_HOST="process-host", VALKEY_PORT=6391)
    with manager.ValkeyClientManager() as client:
        assert client.config.addresses[0].host == "process-host"
        assert client.config.addresses[0].port == 6391
        assert client.config.credentials.password == "dotenv-password"


def test_valkey_env_file_takes_precedence_over_legacy_workshop_file(network, settings):
    legacy = settings.parent / "legacy.env"
    legacy.write_text("VALKEY_PASSWORD=legacy-password\nVALKEY_HOST=legacy-host\n")
    settings.write_text("VALKEY_PASSWORD=preferred-password\nVALKEY_HOST=preferred-host\n")
    configure_env(WORKSHOP_ENV_FILE=str(legacy))
    with manager.ValkeyClientManager() as client:
        assert client.config.credentials.password == "preferred-password"
        assert client.config.addresses[0].host == "preferred-host"


@pytest.mark.parametrize("mode", ["standalone", "cluster"])
def test_context_exception_closes_native_client_without_suppressing_it(network, mode):
    configure_env(VALKEY_MODE=mode, VALKEY_NODES="data-one:6379")
    owner = manager.ValkeyClientManager()
    failure = RuntimeError("caller failed")
    with pytest.raises(RuntimeError) as raised:
        with owner:
            raise failure
    assert raised.value is failure
    assert owner.client is None
    assert network.data_connections[0].close_count == 1


@pytest.mark.parametrize(
    "invalid",
    [
        {"VALKEY_MODE": "redis"},
        {"VALKEY_MODE": "cluster"},
        {"VALKEY_MODE": "cluster", "VALKEY_NODES": "data-one:6379", "VALKEY_DATABASE": "1"},
        {"VALKEY_NODES": "data-one:0"},
        {"VALKEY_NODES": "data-one:65536"},
        {"VALKEY_NODES": "data-one:not-a-port"},
        {"VALKEY_REQUEST_TIMEOUT_MS": "0"},
        {"VALKEY_CONNECTION_TIMEOUT_MS": "-1"},
        {"VALKEY_TLS": "sometimes"},
        {"VALKEY_TLS_CLIENT_CERT": "client.pem"},
        {"VALKEY_TLS": "true", "VALKEY_TLS_CA_CERT": "missing-ca.pem"},
        {"VALKEY_MODE": "sentinel", "VALKEY_SENTINEL_NODES": "sentinel-one:26379"},
        {"VALKEY_MODE": "sentinel", "VALKEY_SENTINEL_SERVICE": "workshop"},
        {
            "VALKEY_MODE": "sentinel",
            "VALKEY_SENTINEL_NODES": "sentinel-one:26379",
            "VALKEY_SENTINEL_SERVICE": "workshop",
            "VALKEY_SENTINEL_REFRESH_MS": "0",
        },
        {
            "VALKEY_MODE": "sentinel",
            "VALKEY_SENTINEL_NODES": "sentinel-one:26379",
            "VALKEY_SENTINEL_SERVICE": "workshop",
            "VALKEY_SENTINEL_TLS": "true",
            "VALKEY_SENTINEL_TLS_CLIENT_CERT": "client.pem",
        },
    ],
)
def test_invalid_settings_fail_before_any_native_connection(network, invalid):
    configure_env(**invalid)
    with pytest.raises((ValueError, FileNotFoundError)):
        with manager.ValkeyClientManager():
            pass
    assert network.factory_calls == []


def test_missing_data_password_fails_before_connecting(network, settings):
    settings.write_text("")
    with pytest.raises(ValueError):
        with manager.ValkeyClientManager():
            pass
    assert network.factory_calls == []


@pytest.mark.parametrize("mode", ["standalone", "cluster"])
def test_tls_files_are_resolved_from_dotenv_directory(network, settings, mode):
    certificate_dir = settings.parent / "certs"
    certificate_dir.mkdir()
    ca = b"test CA PEM"
    certificate = b"test client certificate PEM"
    private_key = b"test client key PEM"
    for name, value in (("ca.pem", ca), ("client.pem", certificate), ("client-key.pem", private_key)):
        (certificate_dir / name).write_bytes(value)
    configure_env(
        VALKEY_MODE=mode,
        VALKEY_NODES="data-one:6379",
        VALKEY_TLS="true",
        VALKEY_TLS_CA_CERT="certs/ca.pem",
        VALKEY_TLS_CLIENT_CERT="certs/client.pem",
        VALKEY_TLS_CLIENT_KEY="certs/client-key.pem",
    )
    with manager.ValkeyClientManager() as client:
        assert client.config.use_tls is True
        tls = client.config.advanced_config.tls_config
        assert tls.root_pem_cacerts == ca
        assert tls.client_cert_pem == certificate
        assert tls.client_key_pem == private_key
        assert tls.use_insecure_tls in (False, None)


def test_sentinel_auth_and_tls_are_independent_of_data_settings(network, settings, clock):
    (settings.parent / "data-ca.pem").write_bytes(b"data CA")
    (settings.parent / "sentinel-ca.pem").write_bytes(b"Sentinel CA")
    sentinel_settings(
        VALKEY_USERNAME="data-user",
        VALKEY_TLS="true",
        VALKEY_TLS_CA_CERT="data-ca.pem",
        VALKEY_SENTINEL_USERNAME="monitor-user",
        VALKEY_SENTINEL_PASSWORD="monitor-password",
        VALKEY_SENTINEL_TLS="true",
        VALKEY_SENTINEL_TLS_CA_CERT="sentinel-ca.pem",
    )
    with manager.ValkeyClientManager() as client:
        assert client.get("key") == b"data-one"
        monitor = network.monitor_connections[0].config
        data = network.data_connections[0].config
        assert monitor.node_discovery_mode is NodeDiscoveryMode.STATIC
        assert monitor.protocol is ProtocolVersion.RESP3
        assert monitor.client_name is None
        assert monitor.credentials.username == "monitor-user"
        assert monitor.credentials.password == "monitor-password"
        assert monitor.advanced_config.tls_config.root_pem_cacerts == b"Sentinel CA"
        assert data.credentials.username == "data-user"
        assert data.credentials.password == "unit-test-password"
        assert data.advanced_config.tls_config.root_pem_cacerts == b"data CA"


def test_sentinel_tls_can_be_disabled_without_disabling_data_tls(network, clock):
    sentinel_settings(VALKEY_TLS="true", VALKEY_SENTINEL_TLS="false")
    with manager.ValkeyClientManager():
        assert network.monitor_connections[0].config.use_tls is False
        assert network.monitor_connections[0].config.credentials is None
        assert network.data_connections[0].config.use_tls is True


def test_sentinel_tls_defaults_enabled_without_inheriting_data_certificates(network, settings, clock):
    for name in ("data-ca.pem", "data-client.pem", "data-key.pem"):
        (settings.parent / name).write_bytes(name.encode())
    sentinel_settings(
        VALKEY_TLS="true",
        VALKEY_TLS_CA_CERT="data-ca.pem",
        VALKEY_TLS_CLIENT_CERT="data-client.pem",
        VALKEY_TLS_CLIENT_KEY="data-key.pem",
    )
    with manager.ValkeyClientManager():
        monitor = network.monitor_connections[0].config
        assert monitor.use_tls is True
        tls = monitor.advanced_config.tls_config
        assert tls.root_pem_cacerts is None
        assert tls.client_cert_pem is None
        assert tls.client_key_pem is None
        assert tls.use_insecure_tls is False


@pytest.mark.parametrize("first_result", [None, ConnectionError("monitor unavailable")])
def test_discovery_tries_next_sentinel_and_verifies_primary(network, clock, first_result):
    sentinel_settings()
    network.monitor_responses["sentinel-one"] = first_result
    with manager.ValkeyClientManager() as client:
        assert client.get("key") == b"data-one"
        assert any(call[1] == ["ROLE"] for call in network.data_connections[0].calls)
    assert {connection.host for connection in network.monitor_connections} == {
        "sentinel-one", "sentinel-two"
    }
    assert all(connection.close_count == 1 for connection in network.created)


def test_stale_sentinel_role_is_rejected_and_next_monitor_is_tried(network, clock):
    sentinel_settings()
    network.monitor_responses["sentinel-one"] = ("stale-replica", 6379)
    network.roles["stale-replica"] = b"slave"
    with manager.ValkeyClientManager() as client:
        assert client.get("key") == b"data-one"
        stale = next(connection for connection in network.data_connections if connection.host == "stale-replica")
        assert stale.close_count == 1


def test_initial_unavailable_sentinels_fail_and_close_controls(network, clock):
    sentinel_settings()
    network.monitor_responses.update(
        {
            "sentinel-one": ConnectionError("first offline"),
            "sentinel-two": ConnectionError("second offline"),
        }
    )
    with pytest.raises(ConnectionError):
        with manager.ValkeyClientManager():
            pass
    assert network.data_connections == []
    assert all(connection.close_count == 1 for connection in network.monitor_connections)


def test_periodic_discovery_replaces_primary_and_preserves_pubsub(network, clock):
    sentinel_settings()
    channels = {"scores"}
    owner = manager.ValkeyClientManager(channels=channels)
    with owner as client:
        first = owner.client
        assert client.get("key") == b"data-one"
        network.primary = ("data-two", 6380)
        clock.advance()
        assert client.get("key") == b"data-two"
        assert owner.client is not first
        assert first.close_count == 1
        for connection in (first, owner.client):
            assert connection.config.pubsub_subscriptions.channels_and_patterns == {
                GlideClientConfiguration.PubSubChannelModes.Exact: channels
            }
    assert all(connection.close_count == 1 for connection in network.data_connections)


def test_broken_role_connection_is_rebuilt_when_primary_address_is_unchanged(
    network, clock, monkeypatch
):
    sentinel_settings()
    owner = manager.ValkeyClientManager()
    with owner as client:
        first = owner.client
        original_command = first.custom_command

        def disconnected_role(arguments, *args, **kwargs):
            if arguments == ["ROLE"]:
                first.calls.append(("custom_command", list(arguments), args, kwargs))
                raise ConnectionError("existing connection dropped")
            return original_command(arguments, *args, **kwargs)

        monkeypatch.setattr(first, "custom_command", disconnected_role)
        clock.advance()
        assert client.set("counter", "one") == b"OK"
        replacement = owner.client
        assert replacement is not first
        assert replacement.host == first.host == "data-one"
        assert first.close_count == 1
        assert any(call[1] == ["ROLE"] for call in replacement.calls)
        assert not any(call[0] == "set" for call in first.calls)
        assert sum(call[0] == "set" for call in replacement.calls) == 1
    assert replacement.close_count == 1


@pytest.mark.parametrize(
    "error",
    [
        ConnectionError("socket dropped"),
        TimeoutError("write outcome unknown"),
        RequestError("READONLY You can't write against a read only replica."),
    ],
)
def test_failover_refresh_propagates_original_error_without_replaying_write(network, clock, error):
    sentinel_settings()
    owner = manager.ValkeyClientManager()
    with owner as client:
        first = owner.client
        network.command_errors[("data-one", "set")] = error
        network.on_command_error = lambda: setattr(network, "primary", ("data-two", 6379))
        with pytest.raises(type(error)) as raised:
            client.set("counter", "one")
        assert raised.value is error
        assert first.close_count == 1
        assert owner.client.host == "data-two"
        writes = [call for connection in network.data_connections for call in connection.calls if call[0] == "set"]
        assert len(writes) == 1
        assert client.get("key") == b"data-two"


def test_non_transport_command_error_does_not_trigger_discovery(network, clock):
    sentinel_settings()
    with manager.ValkeyClientManager() as client:
        controls_before = len(network.monitor_connections)
        error = RequestError("WRONGTYPE Operation against a key holding the wrong kind of value")
        network.command_errors[("data-one", "get")] = error
        with pytest.raises(RequestError) as raised:
            client.get("key")
        assert raised.value is error
        assert len(network.monitor_connections) == controls_before
        assert len(network.data_connections) == 1


def test_monitor_outage_keeps_verified_current_primary(network, clock):
    sentinel_settings()
    owner = manager.ValkeyClientManager()
    with owner as client:
        first = owner.client
        network.monitor_responses.update(
            {
                "sentinel-one": ConnectionError("first offline"),
                "sentinel-two": ConnectionError("second offline"),
            }
        )
        clock.advance()
        assert client.get("key") == b"data-one"
        assert owner.client is first
        assert first.close_count == 0
        assert sum(call[1] == ["ROLE"] for call in first.calls if call[0] == "custom_command") >= 2


def test_observed_stale_primary_does_not_fall_back_to_existing_connection(network, clock):
    sentinel_settings()
    with manager.ValkeyClientManager() as client:
        network.monitor_responses["sentinel-one"] = ("stale-replica", 6379)
        network.monitor_responses["sentinel-two"] = ConnectionError("second offline")
        network.roles["stale-replica"] = b"slave"
        clock.advance()
        with pytest.raises(ConnectionError):
            client.get("key")
        assert not any(
            call[0] == "get"
            for connection in network.data_connections
            for call in connection.calls
        )


def test_unreachable_new_primary_is_not_overridden_by_later_stale_monitor(network, clock):
    sentinel_settings()
    with manager.ValkeyClientManager() as client:
        network.monitor_responses["sentinel-one"] = ("data-two", 6379)
        network.monitor_responses["sentinel-two"] = ("data-one", 6379)
        network.creation_errors["data-two"] = ConnectionError("new primary unreachable")
        clock.advance()
        with pytest.raises(ConnectionError):
            client.get("key")
        assert not any(
            call[0] == "get"
            for connection in network.data_connections
            for call in connection.calls
        )


def test_failed_forced_refresh_does_not_leave_old_refresh_deadline_active(network, clock):
    sentinel_settings()
    failure = TimeoutError("write outcome unknown")
    with manager.ValkeyClientManager() as client:
        network.command_errors[("data-one", "set")] = failure
        network.roles["data-two"] = b"slave"
        network.on_command_error = lambda: setattr(network, "primary", ("data-two", 6379))
        with pytest.raises(TimeoutError) as raised:
            client.set("counter", "one")
        assert raised.value is failure
        # No clock advance: another command must discover again immediately,
        # rather than reuse a future deadline from the previously healthy node.
        with pytest.raises(ConnectionError):
            client.get("key")
        calls = [call for connection in network.data_connections for call in connection.calls]
        assert sum(call[0] == "set" for call in calls) == 1
        assert not any(call[0] == "get" for call in calls)


def test_pubsub_poll_refreshes_before_reading_promoted_primary(network, clock):
    sentinel_settings()
    message = object()
    with manager.ValkeyClientManager(channels={"scores"}) as client:
        network.primary = ("data-two", 6379)
        network.messages["data-two"].append(message)
        clock.advance()
        assert client.try_get_pubsub_message() is message
        assert network.data_connections[0].close_count == 1


def test_blocking_pubsub_get_refreshes_while_waiting(network, clock):
    sentinel_settings(VALKEY_SENTINEL_REFRESH_MS=10)
    message = object()

    def promote_on_first_poll(connection):
        network.poll_hook = None
        network.primary = ("data-two", 6379)
        network.messages["data-two"].append(message)
        clock.advance(0.02)

    with manager.ValkeyClientManager(channels={"scores"}) as client:
        network.poll_hook = promote_on_first_poll
        assert client.get_pubsub_message() is message
        assert network.data_connections[0].close_count == 1


@pytest.mark.parametrize("mode", ["standalone", "cluster"])
def test_subscriptions_use_the_matching_native_client_configuration(network, mode):
    configure_env(VALKEY_MODE=mode, VALKEY_NODES="data-one:6379")
    with manager.ValkeyClientManager(channels={"scores"}) as client:
        cls = GlideClusterClientConfiguration if mode == "cluster" else GlideClientConfiguration
        assert client.config.pubsub_subscriptions.channels_and_patterns == {
            cls.PubSubChannelModes.Exact: {"scores"}
        }
