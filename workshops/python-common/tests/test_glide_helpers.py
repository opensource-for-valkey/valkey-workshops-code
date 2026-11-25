from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import valkey_client_manager as helpers


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ([0], []),
        ([1, {b"movie:1": {}}], [b"movie:1"]),
        ([2, {b"movie:1": {}, b"movie:2": {}}], [b"movie:1", b"movie:2"]),
    ],
)
def test_search_parses_native_document_mapping_and_empty_result(reply, expected):
    class Client:
        def custom_command(self, arguments):
            assert arguments[0] == "FT.SEARCH"
            assert arguments[arguments.index("vector") + 1] == b"\x00\x01"
            return reply

    assert helpers.search_document_keys(Client(), "movies", b"\x00\x01", 3) == expected


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ([0], []),
        ([1, b"movie:1"], [b"movie:1"]),
        ([2, b"movie:1", b"movie:2"], [b"movie:1", b"movie:2"]),
        ([1, b"movie:1", [b"title", b"Orbit"]], [b"movie:1"]),
        (
            [2, b"movie:1", [b"title", b"Orbit"], b"movie:2", [b"title", b"Tide"]],
            [b"movie:1", b"movie:2"],
        ),
        ([1, {b"movie:1": {b"title": b"Orbit"}}], [b"movie:1"]),
    ],
)
def test_search_reply_keys_accepts_positional_and_mapping_replies(reply, expected):
    assert helpers.search_reply_keys(reply) == expected


def test_search_reply_keys_rejects_unknown_shape():
    with pytest.raises(TypeError):
        helpers.search_reply_keys([1, 42])


def test_scan_follows_binary_cursor_until_zero():
    class Client:
        def scan(self, cursor, *, match, count):
            assert match == "workshop:*"
            return [b"7", [b"workshop:1"]] if cursor == "0" else [b"0", [b"workshop:2"]]

    assert list(helpers.scan_keys(Client(), "workshop:*")) == [
        b"workshop:1",
        b"workshop:2",
    ]


def test_manager_loads_selected_dotenv_and_closes_one_owned_client(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(helpers.os, "environ", dict(helpers.os.environ))
    settings = tmp_path / "private.env"
    settings.write_text("VALKEY_HOST=127.0.0.2\nVALKEY_PORT=6382\n")
    monkeypatch.setenv("WORKSHOP_ENV_FILE", str(settings))
    monkeypatch.delenv("VALKEY_HOST", raising=False)
    monkeypatch.delenv("VALKEY_PORT", raising=False)
    clients = []

    class Client:
        closed = False

        @classmethod
        def create(cls, configuration):
            assert configuration.addresses[0].host == "127.0.0.2"
            assert configuration.addresses[0].port == 6382
            client = cls()
            clients.append(client)
            return client

        def close(self):
            self.closed = True

    monkeypatch.setattr(helpers, "GlideClient", Client)
    with helpers.ValkeyClientManager() as manager:
        assert manager.client is manager.client
        assert len(clients) == 1
    assert clients[0].closed


def test_environment_setup_reuses_provisioned_secret_without_printing_it(
    tmp_path, monkeypatch, capsys
):
    import setup_env
    from dotenv import dotenv_values

    monkeypatch.setattr(helpers.os, "environ", dict(helpers.os.environ))
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("VALKEY_PASSWORD", raising=False)
    monkeypatch.setenv("WORKSHOP_ENV_FILE", str(tmp_path / ".env"))
    credentials = tmp_path / "provisioned.env"
    credentials.write_text("VALKEY_PASSWORD=unit-test-placeholder\n")
    monkeypatch.setenv("WORKSHOP_CREDENTIALS_FILE", str(credentials))
    (tmp_path / ".env.example").write_text("VALKEY_PASSWORD=\n")
    setup_env.main()
    assert (
        dotenv_values(tmp_path / ".env")["VALKEY_PASSWORD"] == "unit-test-placeholder"
    )
    assert (tmp_path / ".env").stat().st_mode & 0o777 == 0o600
    assert "unit-test-placeholder" not in capsys.readouterr().out
    credentials.write_text("VALKEY_PASSWORD=changed-placeholder\n")
    setup_env.main()
    assert (
        dotenv_values(tmp_path / ".env")["VALKEY_PASSWORD"] == "unit-test-placeholder"
    )
