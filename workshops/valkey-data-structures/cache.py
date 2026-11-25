"""Build cache-aside and report source, Valkey, and total response latency."""

from dataclasses import dataclass
import json
import math
import time

from glide_sync import ConnectionError, ExpirySet, ExpiryType, TimeoutError
from rich.table import Table

from common import LatencyTimer, console, key, timed
from valkey_client import ValkeyClientManager


@dataclass
class CacheLatency:
    """Client-observed milliseconds for one response; None means not used."""

    total_ms: float = 0.0
    cache_read_ms: float | None = None
    source_read_ms: float | None = None
    cache_write_ms: float | None = None
    cache_read_status: str = "not used"
    cache_write_status: str = "not used"

    def reset(self):
        self.total_ms = 0.0
        self.cache_read_ms = self.source_read_ms = self.cache_write_ms = None
        self.cache_read_status = self.cache_write_status = "not used"


def fetch_product(sku):
    """Stand in for a slow database or upstream API; this is a simulated source."""
    time.sleep(0.020)
    return {"sku": sku, "name": "Conference speaker", "price_cents": 4999}


def product_key(sku):
    return key("cache", "product", "v1", sku)


def load_product(client, sku, ttl=30, *, latency: CacheLatency | None = None):
    """Return (product, path), optionally recording each phase and total time."""
    timings = latency if latency is not None else CacheLatency()
    timings.reset()
    try:
        with LatencyTimer() as response:
            timings.cache_read_status = "failed"
            try:
                with LatencyTimer() as lookup:
                    cached = client.get(product_key(sku))
                timings.cache_read_status = "hit" if cached is not None else "miss"
            except (ConnectionError, TimeoutError):
                cached = None
                timings.cache_read_status = "unavailable"
            finally:
                timings.cache_read_ms = lookup.elapsed_ms
            if cached is not None:
                return json.loads(cached), "hit"

            try:
                with LatencyTimer() as source:
                    product = fetch_product(sku)
            finally:
                timings.source_read_ms = source.elapsed_ms
            serialized = json.dumps(product)
            timings.cache_write_status = "failed"
            try:
                with LatencyTimer() as store:
                    client.set(
                        product_key(sku), serialized,
                        expiry=ExpirySet(ExpiryType.SEC, ttl),
                    )
                timings.cache_write_status = "stored"
            except (ConnectionError, TimeoutError):
                # Do not discard a successful source read when the cache is down.
                timings.cache_write_status = "unavailable"
            finally:
                timings.cache_write_ms = store.elapsed_ms
            return product, "source"
    finally:
        timings.total_ms = response.elapsed_ms


def print_response(label, product, path, latency):
    """Keep timing beside the returned payload and identify skipped phases."""
    def phase(milliseconds, status=None):
        if milliseconds is None:
            return "not used"
        suffix = f" ({status})" if status is not None else ""
        return f"{milliseconds:.3f} ms{suffix}"

    console.print(f"{label}: {path}; total latency={latency.total_ms:.3f} ms")
    console.print_json(data=product)
    console.print(
        f"Valkey GET: {phase(latency.cache_read_ms, latency.cache_read_status)}; "
        f"source read: {phase(latency.source_read_ms)}; "
        f"Valkey SET: {phase(latency.cache_write_ms, latency.cache_write_status)}"
    )


def measure(operation, samples):
    durations = []
    for _ in range(samples):
        _, elapsed_ms = timed(operation)
        durations.append(elapsed_ms)
    durations.sort()
    return {
        percentile: durations[math.ceil(percentile * samples / 100) - 1]
        for percentile in (50, 95)
    }


def demonstrate(client):
    sku = "speaker"
    direct, direct_ms = timed(fetch_product, sku)
    print_response("Direct source of truth", direct, "source", CacheLatency(
        total_ms=direct_ms, source_read_ms=direct_ms,
    ))
    removed, removed_ms = timed(client.delete, [product_key(sku)])
    console.print(f"Initial invalidation: DEL returned {removed}; Valkey latency={removed_ms:.3f} ms")

    cold_latency, warm_latency = CacheLatency(), CacheLatency()
    cold, cold_path = load_product(client, sku, latency=cold_latency)
    warm, warm_path = load_product(client, sku, latency=warm_latency)
    assert direct == cold == warm and cold_path == "source" and warm_path == "hit"
    print_response("First request", cold, cold_path, cold_latency)
    print_response("Second request", warm, warm_path, warm_latency)
    ttl, ttl_ms = timed(client.ttl, product_key(sku))
    console.print(f"Cache key: {product_key(sku)}; TTL: {ttl} s; Valkey latency={ttl_ms:.3f} ms")

    source = measure(lambda: fetch_product(sku), 40)

    def cache_hit():
        _, path = load_product(client, sku)
        assert path == "hit", "Cache expired or unavailable during the warm benchmark"

    cached = measure(cache_hit, 100)
    table = Table(title="Cache-aside latency · local measurements")
    table.add_column("Path")
    table.add_column("p50 (ms)", justify="right")
    table.add_column("p95 (ms)", justify="right")
    for label, timings in (("Simulated source response (40 samples)", source),
                           ("Warm cache response (100 samples)", cached)):
        table.add_row(label, f"{timings[50]:.3f}", f"{timings[95]:.3f}")
    console.print(table)
    console.print(
        "Client-observed timings exclude initial connection setup and terminal output. "
        "The source has an intentional 20 ms delay; warm responses include GET and JSON decoding."
    )
    console.print("These are local measurements, not a production latency guarantee.")

    removed, removed_ms = timed(client.delete, [product_key(sku)])
    console.print(f"Invalidate after an authoritative update: DEL returned {removed}; Valkey latency={removed_ms:.3f} ms")
    invalidated_latency = CacheLatency()
    product, path = load_product(client, sku, latency=invalidated_latency)
    assert path == "source"
    print_response("After invalidation", product, path, invalidated_latency)


def main():
    with ValkeyClientManager() as client:
        demonstrate(client)


if __name__ == "__main__":
    main()
