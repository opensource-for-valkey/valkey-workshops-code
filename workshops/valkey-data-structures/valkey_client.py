"""Own native GLIDE connections for standalone, Sentinel, and cluster labs."""

import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
from glide_sync import (
    AdvancedGlideClientConfiguration,
    AdvancedGlideClusterClientConfiguration,
    ClosingError,
    ConnectionError,
    GlideClient,
    GlideClientConfiguration,
    GlideClusterClient,
    GlideClusterClientConfiguration,
    GlideError,
    NodeAddress,
    NodeDiscoveryMode,
    RequestError,
    ServerCredentials,
    TimeoutError,
    TlsAdvancedConfiguration,
)


def load_settings() -> Path:
    """Read the selected .env; exported values take precedence over the file."""
    selected = os.environ.get("VALKEY_ENV_FILE") or os.environ.get("WORKSHOP_ENV_FILE")
    path = Path(selected).expanduser() if selected else Path(__file__).with_name(".env")
    path = path.resolve()
    if selected and not path.is_file():
        raise ValueError("VALKEY_ENV_FILE must name an existing environment file.")
    load_dotenv(path, override=False)
    return path


def _value(name: str, default: str = "") -> str:
    return os.environ.get(name, "").strip() or default


def _integer(name: str, default: int, *, minimum: int = 1, maximum=None) -> int:
    try:
        value = int(_value(name, str(default)))
    except ValueError:
        raise ValueError(f"{name} must be an integer.") from None
    if value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"{name} is outside its allowed range.")
    return value


def _boolean(name: str, default: bool = False) -> bool:
    value = _value(name, str(default)).lower()
    if value not in {"true", "false", "1", "0"}:
        raise ValueError(f"{name} must be true or false.")
    return value in {"true", "1"}


def _nodes(name: str) -> tuple[NodeAddress, ...]:
    """Parse host:port seeds, including [IPv6]:port, without guessing ports."""
    result = []
    for entry in _value(name).split(","):
        entry = entry.strip()
        if entry.startswith("[") and "]:" in entry:
            host, port = entry[1:].split("]:", 1)
        elif entry.count(":") == 1:
            host, port = entry.split(":", 1)
        else:
            raise ValueError(f"{name} requires comma-separated host:port endpoints.")
        try:
            number = int(port)
        except ValueError:
            raise ValueError(f"{name} contains an invalid port.") from None
        if not host.strip() or not 1 <= number <= 65535:
            raise ValueError(f"{name} contains an invalid endpoint.")
        result.append(NodeAddress(host.strip(), number))
    return tuple(result)


@dataclass(frozen=True)
class _TLS:
    enabled: bool
    config: TlsAdvancedConfiguration | None = field(repr=False)


def _tls(prefix: str, env_file: Path, default: bool = False) -> _TLS:
    enabled = _boolean(prefix, default)
    paths = [_value(f"{prefix}_{suffix}") for suffix in (
        "CA_CERT", "CLIENT_CERT", "CLIENT_KEY"
    )]
    if any(paths) and not enabled:
        raise ValueError(f"Enable {prefix} before setting its certificate files.")
    if bool(paths[1]) != bool(paths[2]):
        raise ValueError(f"{prefix}_CLIENT_CERT and {prefix}_CLIENT_KEY must be paired.")
    if not enabled:
        return _TLS(False, None)
    contents = []
    for name in paths:
        if not name:
            contents.append(None)
            continue
        path = Path(name).expanduser()
        if not path.is_absolute():
            path = env_file.parent / path
        try:
            contents.append(path.read_bytes())
        except OSError:
            raise ValueError(f"A {prefix} certificate file could not be read.") from None
    return _TLS(True, TlsAdvancedConfiguration(
        use_insecure_tls=False,
        root_pem_cacerts=contents[0],
        client_cert_pem=contents[1],
        client_key_pem=contents[2],
    ))


@dataclass(frozen=True)
class _Settings:
    mode: str
    nodes: tuple[NodeAddress, ...]
    credentials: ServerCredentials = field(repr=False)
    database: int
    request_timeout: int
    connection_timeout: int
    client_name: str
    tls: _TLS
    sentinel_nodes: tuple[NodeAddress, ...]
    sentinel_service: str
    sentinel_credentials: ServerCredentials | None = field(repr=False)
    sentinel_tls: _TLS
    sentinel_refresh_ms: int

    @classmethod
    def read(cls, env_file: Path):
        mode = _value("VALKEY_MODE", "standalone").lower()
        if mode not in {"standalone", "sentinel", "cluster"}:
            raise ValueError("VALKEY_MODE must be standalone, sentinel, or cluster.")
        password = os.environ.get("VALKEY_PASSWORD")
        if not password:
            raise ValueError("Set VALKEY_PASSWORD; use `uv run python setup_env.py` for the lab.")
        database = _integer("VALKEY_DATABASE", 0, minimum=0)
        if mode == "cluster" and database != 0:
            raise ValueError("VALKEY_DATABASE must be 0 in cluster mode.")
        if _value("VALKEY_NODES"):
            nodes = _nodes("VALKEY_NODES")
        elif mode == "cluster":
            raise ValueError("Set VALKEY_NODES to the cluster's host:port seed nodes.")
        else:
            nodes = (NodeAddress(
                _value("VALKEY_HOST", "127.0.0.1"),
                _integer("VALKEY_PORT", 6381, maximum=65535),
            ),)
        tls = _tls("VALKEY_TLS", env_file)
        sentinel_nodes = ()
        sentinel_service = ""
        sentinel_credentials = None
        sentinel_tls = _TLS(False, None)
        if mode == "sentinel":
            sentinel_nodes = _nodes("VALKEY_SENTINEL_NODES")
            sentinel_service = _value("VALKEY_SENTINEL_SERVICE")
            if not sentinel_service:
                raise ValueError("Set VALKEY_SENTINEL_SERVICE to the monitored service name.")
            sentinel_password = os.environ.get("VALKEY_SENTINEL_PASSWORD")
            if sentinel_password:
                sentinel_credentials = ServerCredentials(
                    password=sentinel_password,
                    username=_value("VALKEY_SENTINEL_USERNAME", "default"),
                )
            sentinel_tls = _tls("VALKEY_SENTINEL_TLS", env_file, tls.enabled)
        return cls(
            mode, nodes,
            ServerCredentials(password=password, username=_value("VALKEY_USERNAME", "default")),
            database,
            _integer("VALKEY_REQUEST_TIMEOUT_MS", 5000),
            _integer("VALKEY_CONNECTION_TIMEOUT_MS", 3000),
            _value("VALKEY_CLIENT_NAME", "valkey-data-structures-workshop"),
            tls, sentinel_nodes, sentinel_service, sentinel_credentials, sentinel_tls,
            _integer("VALKEY_SENTINEL_REFRESH_MS", 1000),
        )


class ValkeyClientManager:
    """Configure, create, and close native clients; Sentinel follows promotion."""

    def __init__(self, *, channels: set[str] | None = None):
        self.env_file = load_settings()
        self.channels = set(channels or ())
        self.client: GlideClient | GlideClusterClient | None = None
        self.settings: _Settings | None = None
        self._master: tuple[str, int] | None = None
        self._next_refresh = 0.0
        self._closed = True
        self._lock = threading.RLock()

    def _subscriptions(self, config_type):
        if not self.channels:
            return None
        return config_type.PubSubSubscriptions(
            channels_and_patterns={config_type.PubSubChannelModes.Exact: self.channels},
            callback=None, context=None,
        )

    def _data_config(self, addresses, *, cluster=False, sentinel=False):
        settings = self.settings
        config_type = GlideClusterClientConfiguration if cluster else GlideClientConfiguration
        advanced_type = (
            AdvancedGlideClusterClientConfiguration if cluster
            else AdvancedGlideClientConfiguration
        )
        options = dict(
            addresses=list(addresses),
            use_tls=settings.tls.enabled,
            credentials=settings.credentials,
            database_id=settings.database,
            request_timeout=settings.request_timeout,
            client_name=settings.client_name,
            pubsub_subscriptions=self._subscriptions(config_type),
            advanced_config=advanced_type(
                connection_timeout=settings.connection_timeout,
                tls_config=settings.tls.config,
            ),
        )
        if sentinel:
            # Sentinel selects the endpoint; verify ROLE ourselves before using it.
            options["node_discovery_mode"] = NodeDiscoveryMode.STATIC
        return config_type(**options)

    def __enter__(self):
        with self._lock:
            if not self._closed:
                raise RuntimeError("This ValkeyClientManager is already open.")
            self.settings = _Settings.read(self.env_file)
            self._closed = False
            try:
                if self.settings.mode == "sentinel":
                    self._refresh(force=True)
                    return _SentinelClient(self)
                if self.settings.mode == "cluster":
                    self.client = GlideClusterClient.create(
                        self._data_config(self.settings.nodes, cluster=True)
                    )
                else:
                    self.client = GlideClient.create(self._data_config(self.settings.nodes))
                return self.client
            except BaseException:
                self.close()
                raise

    @staticmethod
    def _is_primary(client) -> bool:
        reply = client.custom_command(["ROLE"])
        return bool(reply) and reply[0] in {b"master", "master"}

    def _refresh(self, *, force=False):
        """Resolve Sentinel and verify ROLE. Called with the manager lock held."""
        if self._closed:
            raise ClosingError("The Valkey client manager is closed.")
        if not force and time.monotonic() < self._next_refresh:
            return
        # If discovery fails, the next command must try again immediately.
        self._next_refresh = 0.0
        settings = self.settings
        saw_other_primary = False
        for endpoint in settings.sentinel_nodes:
            monitor = candidate = None
            try:
                monitor = GlideClient.create(GlideClientConfiguration(
                    addresses=[endpoint],
                    use_tls=settings.sentinel_tls.enabled,
                    credentials=settings.sentinel_credentials,
                    request_timeout=settings.request_timeout,
                    node_discovery_mode=NodeDiscoveryMode.STATIC,
                    advanced_config=AdvancedGlideClientConfiguration(
                        connection_timeout=settings.connection_timeout,
                        tls_config=settings.sentinel_tls.config,
                    ),
                ))
                reply = monitor.custom_command([
                    "SENTINEL", "get-master-addr-by-name", settings.sentinel_service
                ])
                if not isinstance(reply, (list, tuple)) or len(reply) != 2:
                    continue
                host = reply[0].decode() if isinstance(reply[0], bytes) else str(reply[0])
                port = int(reply[1])
                if not host or not 1 <= port <= 65535:
                    continue
                address = (host, port)
                if saw_other_primary and address == self._master:
                    continue
                saw_other_primary |= address != self._master
                reuse = address == self._master and self.client is not None and not force
                if reuse:
                    try:
                        if not self._is_primary(self.client):
                            continue
                    except GlideError:
                        reuse = False
                if not reuse:
                    candidate = GlideClient.create(self._data_config(
                        [NodeAddress(host, port)], sentinel=True
                    ))
                    if not self._is_primary(candidate):
                        continue
                    previous = self.client
                    self.client, candidate = candidate, None
                    self._master = address
                    if previous is not None:
                        previous.close()
                self._next_refresh = time.monotonic() + settings.sentinel_refresh_ms / 1000
                return
            except (GlideError, ValueError, UnicodeError):
                continue
            finally:
                if candidate is not None:
                    candidate.close()
                if monitor is not None:
                    monitor.close()
        # A healthy primary can serve during a monitor outage. Once a different
        # primary is announced, never fall back to the previous primary.
        if self.client is not None and not saw_other_primary and not force:
            try:
                if self._is_primary(self.client):
                    self._next_refresh = time.monotonic() + settings.sentinel_refresh_ms / 1000
                    return
            except GlideError:
                pass
        raise ConnectionError("Sentinel could not provide a reachable, verified primary.")

    def close(self):
        with self._lock:
            self._closed = True
            if self.client is not None:
                client, self.client = self.client, None
                client.close()
            self._master = None
            self._next_refresh = 0.0

    def __exit__(self, *_exc):
        self.close()


class _SentinelClient:
    """Delegate to native GLIDE, refreshing connections without replaying writes."""

    def __init__(self, manager: ValkeyClientManager):
        self._manager = manager

    def _call(self, name, *args, **kwargs):
        manager = self._manager
        with manager._lock:
            manager._refresh()
            try:
                return getattr(manager.client, name)(*args, **kwargs)
            except (ConnectionError, TimeoutError, ClosingError, RequestError) as error:
                reconnect = isinstance(error, (ConnectionError, TimeoutError, ClosingError))
                reconnect |= str(error).lstrip().startswith("READONLY")
                if reconnect:
                    try:
                        manager._refresh(force=True)
                    except GlideError:
                        pass
                # A lost response does not prove a write failed. Let the caller
                # choose recovery; never submit the original operation again.
                raise

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return lambda *args, **kwargs: self._call(name, *args, **kwargs)

    def get_pubsub_message(self):
        # Polling allows a waiting subscriber to rediscover a promoted primary.
        # Recreated subscriptions receive new messages; Pub/Sub has no replay.
        while True:
            message = self._call("try_get_pubsub_message")
            if message is not None:
                return message
            time.sleep(0.05)

    def close(self):
        self._manager.close()
