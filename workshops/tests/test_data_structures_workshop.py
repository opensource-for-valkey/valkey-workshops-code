"""Exercise the workshop's real commands against an explicitly selected server."""

import importlib
import json
import os
from pathlib import Path
import re
import select
import signal
import subprocess
import time
from uuid import uuid4

import pytest


ASSETS = Path(__file__).resolve().parents[1] / "valkey-data-structures"
pytestmark = pytest.mark.skipif(
    os.environ.get("VALKEY_WORKSHOP_INTEGRATION") != "1",
    reason="Set VALKEY_WORKSHOP_INTEGRATION=1 for real-Valkey integration tests",
)


@pytest.fixture
def lab(monkeypatch):
    monkeypatch.syspath_prepend(str(ASSETS))
    monkeypatch.setenv("VALKEY_KEY_PREFIX", f"test-{uuid4().hex}")
    common = importlib.import_module("common")
    with common.get_client() as client:
        assert client.ping()
        yield client, common.key
        names = list(common.scan_keys(client, f"{common.key()}:*"))
        if names:
            client.unlink(names)


def script_command(name, *args):
    return [
        "uv", "run", "--locked", "--project", str(ASSETS), "--group", "test",
        "python", str(ASSETS / name), *args,
    ]


def run_script(name, *args, expected_status=0):
    result = subprocess.run(
        script_command(name, *args),
        capture_output=True,
        text=True,
        timeout=20,
        env=os.environ.copy(),
    )
    assert result.returncode == expected_status, result.stdout + result.stderr
    return result.stdout


def read_line(process):
    ready, _, _ = select.select([process.stdout], [], [], 5)
    assert ready, "Subscriber did not produce output within five seconds"
    line = process.stdout.readline()
    assert line, "Subscriber exited unexpectedly"
    return line


def wait_for_subscriptions(client, channel, expected, timeout=5):
    """Wait for native cluster Pub/Sub state to converge across nodes."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        count = client.pubsub_numsub([channel])[channel.encode()]
        if count == expected:
            return
        time.sleep(0.05)
    assert count == expected, f"Expected {expected} subscribers, observed {count}"


def test_cache_hit_expiry_invalidation_and_failure_fallback(lab, monkeypatch):
    client, _ = lab
    cache = importlib.import_module("cache")
    calls = []

    def source(sku):
        calls.append(sku)
        return {"sku": sku, "revision": len(calls)}

    monkeypatch.setattr(cache, "fetch_product", source)
    assert cache.load_product(client, "test", ttl=1)[1] == "source"
    assert cache.load_product(client, "test")[1] == "hit"
    assert len(calls) == 1
    time.sleep(1.1)
    assert cache.load_product(client, "test")[0]["revision"] == 2
    client.delete([cache.product_key("test")])
    assert cache.load_product(client, "test")[0]["revision"] == 3

    from glide_sync import ConnectionError, RequestError

    class Unavailable:
        def get(self, *_args):
            raise ConnectionError("cache unavailable")

        def set(self, *_args, **_kwargs):
            raise ConnectionError("cache unavailable")

    assert cache.load_product(Unavailable(), "test")[0]["revision"] == 4

    class BadCredentials(Unavailable):
        def get(self, *_args):
            raise RequestError("invalid credentials")

    with pytest.raises(RequestError):
        cache.load_product(BadCredentials(), "test")

    class BadWriteCredentials(Unavailable):
        def get(self, *_args):
            return None

        def set(self, *_args, **_kwargs):
            raise RequestError("invalid credentials")

    with pytest.raises(RequestError):
        cache.load_product(BadWriteCredentials(), "test")


def test_sessions_share_state_and_never_recreate_expired_keys(lab):
    client, _ = lab
    sessions = importlib.import_module("sessions")
    common = importlib.import_module("common")
    with common.get_client() as other:
        sessions.create_session(client, "test-session", "u42", ttl=10)
        assert sessions.read_session(other, "test-session")["user_id"] == "u42"
        assert sessions.update_session(other, "test-session", "dark") == 1
        assert sessions.update_session(client, "test-session", "blue") == 2
        assert sessions.read_session(other, "test-session")["visits"] == "2"
        assert 0 < client.ttl(sessions.session_key("test-session")) <= 10
        client.pexpire(sessions.session_key("test-session"), 1)
        time.sleep(0.02)
        assert sessions.update_session(other, "test-session", "light") is None
        assert not client.exists([sessions.session_key("test-session")])


def test_leaderboard_score_changes_rank_and_tie_order(lab):
    client, key = lab
    leaderboard = importlib.import_module("leaderboard")
    board = key("leaderboard", "test")
    for player, score in {"alice": 100, "bob": 100, "carol": 90}.items():
        leaderboard.record_score(client, board, player, score)
    assert leaderboard.top_players(client, board, 3) == [
        ("bob", 100.0), ("alice", 100.0), ("carol", 90.0)
    ]
    assert leaderboard.player_rank(client, board, "bob") == 1
    assert leaderboard.player_rank(client, board, "absent") is None
    leaderboard.add_points(client, board, "carol", 20)
    assert leaderboard.player_rank(client, board, "carol") == 1
    assert client.custom_command(["MEMORY", "USAGE", board]) > 0


def test_pubsub_fans_out_and_has_no_offline_replay(lab):
    client, key = lab
    subscribers = [
        subprocess.Popen(
            script_command("events.py", "subscribe"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=os.environ.copy(),
        )
        for _ in range(2)
    ]
    try:
        for process in subscribers:
            ready = read_line(process)
            assert ready.startswith("READY:")
            assert re.search(r"setup: \d+\.\d{3} ms", ready), ready
        wait_for_subscriptions(client, key("events", "scores"), 2)
        output = run_script("events.py", "publish")
        event = json.loads(output[:output.rfind("}") + 1])
        reported = re.search(r"Publishing node reported (\d+) subscriptions", output)
        assert reported, output
        assert re.search(r"PUBLISH response: \d+\.\d{3} ms", output), output
        from glide_sync import GlideClusterClient
        count = int(reported.group(1))
        if isinstance(client, GlideClusterClient):
            assert 0 <= count <= 2
        else:
            assert count == 2
        for process in subscribers:
            received = read_line(process)
            assert event["event_id"] in received
            assert re.search(r"dequeue call: \d+\.\d{3} ms", received), received
            assert "event age (clock-dependent):" in received
    finally:
        for process in subscribers:
            process.send_signal(signal.SIGINT)
            process.communicate(timeout=5)
    wait_for_subscriptions(client, key("events", "scores"), 0)
    assert "Publishing node reported 0 subscriptions" in run_script("events.py", "publish")
    manager = importlib.import_module("valkey_client")
    with manager.ValkeyClientManager(channels={key("events", "scores")}) as subscriber:
        wait_for_subscriptions(client, key("events", "scores"), 1)
        time.sleep(0.1)
        assert subscriber.try_get_pubsub_message() is None


def test_queue_preserves_fifo_claim_and_recovers_duplicate_effect(lab):
    client, key = lab
    run_script("queues.py", "enqueue", "--count", "3")
    oldest = client.lindex(key("queue", "ready"), -1)
    pending = key("queue", "processing", "worker-a")
    run_script(
        "queues.py", "work", "--worker", "worker-a", "--crash-after-claim",
        expected_status=2,
    )
    assert client.lrange(pending, 0, -1) == [oldest]
    assert client.llen(key("queue", "ready")) == 2
    assert client.hlen(key("queue", "results")) == 0
    run_script("queues.py", "work", "--worker", "worker-a", expected_status=1)
    run_script("queues.py", "recover", "--worker", "worker-a", expected_status=1)
    assert client.llen(pending) == 1
    run_script("queues.py", "recover", "--worker", "worker-a", "--stopped")
    run_script("queues.py", "work", "--worker", "worker-a")
    assert client.hlen(key("queue", "results")) == 3
    assert client.llen(pending) == client.llen(key("queue", "ready")) == 0

    run_script("queues.py", "enqueue", "--count", "1")
    run_script(
        "queues.py", "work", "--worker", "worker-a", "--crash-after-effect",
        expected_status=2,
    )
    assert client.hlen(key("queue", "results")) == 4
    assert client.llen(pending) == 1
    run_script("queues.py", "recover", "--worker", "worker-a", "--stopped")
    output = run_script("queues.py", "work", "--worker", "worker-a")
    assert "duplicate effect skipped" in output
    assert client.hlen(key("queue", "results")) == 4
    assert client.llen(pending) == 0


def test_reference_entrypoints_and_cleanup_keep_other_prefixes(lab):
    client, key = lab
    other = f"other-{uuid4().hex}:keep"
    client.set(other, "preserve")
    try:
        for name in (
            "common.py", "binary_strings.py", "cache.py", "sessions.py",
            "leaderboard.py", "benchmark.py",
        ):
            output = run_script(name)
            assert re.search(r"\d+\.\d{3} ms", output), f"Missing measured latency: {name}\n{output}"
        output = run_script("cleanup.py")
        assert re.search(r"SCAN \+ UNLINK latency: \d+\.\d{3} ms", output), output
        common = importlib.import_module("common")
        assert not list(common.scan_keys(client, f"{key()}:*"))
        assert client.get(other) == b"preserve"
    finally:
        client.delete([other])


def test_binary_strings_preserve_file_and_opaque_bytes_and_use_byte_offsets(lab):
    import gzip

    client, key = lab
    binary = importlib.import_module("binary_strings")
    binary.demonstrate(client)
    values = binary.sample_values()
    assert client.get(key("string", "logo-svg")) == (
        ASSETS / "assets/valkey-horizontal.svg"
    ).read_bytes()
    assert gzip.decompress(client.get(key("string", "logo-svg-gzip"))) == values["logo-svg"]
    assert client.get(key("string", "opaque")) == b"\x00\x01\xff\x80A"
    assert client.strlen(key("string", "utf8")) == 10
    assert client.getrange(key("string", "utf8"), 0, 4).decode("utf-8") == "café"
    assert client.getrange(key("string", "utf8"), 6, 9).decode("utf-8") == "🚀"
    with pytest.raises(UnicodeDecodeError):
        client.getrange(key("string", "utf8"), 3, 3).decode("utf-8")


def test_textual_dashboard_observes_native_glide_state(lab):
    """Exercise actual widget updates and native GLIDE reads in a headless TUI."""
    import asyncio

    client, _ = lab
    dashboard = importlib.import_module("dashboard")

    async def check():
        async with dashboard.WorkshopDashboard(client).run_test() as pilot:
            await pilot.pause()
            table = pilot.app.query_one(dashboard.DataTable)
            assert table.row_count == 5
            assert len(table.columns) == 4
            for row in range(5):
                assert float(table.get_cell_at((row, 1))) >= 0
            assert "refresh:" in str(pilot.app.query_one("#status", dashboard.Static).content)
            assert "GLIDE" in str(pilot.app.query_one("#status", dashboard.Static).content)
            await pilot.press("r")
            assert table.row_count == 5

    asyncio.run(check())
