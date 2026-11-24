"""Connection and key naming shared by the five workshop patterns."""

import os
import re
import time

from glide_sync import Batch, ClusterBatch, ClusterScanCursor, GlideClusterClient
from rich.console import Console
from rich.panel import Panel

from valkey_client import ValkeyClientManager, load_settings

env_file = load_settings()
console = Console(highlight=False, markup=False, soft_wrap=True)


class LatencyTimer:
    """Measure client-observed work, including failed calls, in milliseconds."""

    def __enter__(self):
        self.elapsed_ms = None
        self.started_ns = time.perf_counter_ns()
        return self

    def __exit__(self, *_exc):
        self.elapsed_ms = (time.perf_counter_ns() - self.started_ns) / 1_000_000


def timed(operation, *args, **kwargs):
    """Return (result, milliseconds); preserve the operation's exception behavior."""
    with LatencyTimer() as timer:
        result = operation(*args, **kwargs)
    return result, timer.elapsed_ms


def text(value: bytes | str) -> str:
    """GLIDE returns bytes; decode only at the application boundary."""
    return value.decode("utf-8") if isinstance(value, bytes) else value


def scan_keys(client, pattern: str, count: int = 100):
    """Iterate native standalone or cluster SCAN pages, preserving key bytes."""
    if isinstance(client, GlideClusterClient):
        cursor = ClusterScanCursor()
        while not cursor.is_finished():
            cursor, names = client.scan(cursor, match=pattern, count=count)
            yield from names
        return
    cursor = b"0"
    while True:
        cursor, names = client.scan(cursor, match=pattern, count=count)
        yield from names
        if cursor == b"0":
            return


def new_batch(client, *, is_atomic: bool):
    """Choose the native batch type required by this GLIDE client."""
    batch_type = ClusterBatch if isinstance(client, GlideClusterClient) else Batch
    return batch_type(is_atomic=is_atomic)


def key(*parts: str) -> str:
    prefix = os.environ.get("VALKEY_KEY_PREFIX", "ds")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", prefix):
        raise ValueError("VALKEY_KEY_PREFIX must contain 1–48 letters, digits, _ or -")
    if parts and parts[0] == "queue":
        # LMOVE/BLMOVE require related queue keys to share a Cluster slot.
        return ":".join((prefix, "queue", "{reports}", *parts[1:]))
    return ":".join((prefix, *parts))


def get_client() -> ValkeyClientManager:
    """A convenience entry point; the manager owns the native GLIDE client."""
    return ValkeyClientManager()


if __name__ == "__main__":
    with get_client() as client:
        reply, latency_ms = timed(client.ping)
        assert text(reply) == "PONG"
        console.print(Panel(
            f"PONG - GLIDE connected; PING latency: {latency_ms:.3f} ms\nKey prefix: {key()}\nConfiguration: {env_file.name}",
            title="Workshop ready",
            border_style="blue",
        ))
