"""Check cache timing boundaries without depending on machine speed."""

from io import StringIO
import json
from pathlib import Path
import sys

import pytest
from glide_sync import ConnectionError, RequestError, TimeoutError
from rich.console import Console

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB))
import cache  # noqa: E402
import common  # noqa: E402


PRODUCT = {"sku": "speaker", "name": "Conference speaker", "price_cents": 4999}


class Clock:
    def __init__(self):
        self.now = 0

    def __call__(self):
        return self.now

    def advance(self, milliseconds):
        self.now += int(milliseconds * 1_000_000)


class FakeClient:
    def __init__(self, clock, *, cached=None, read_error=None, write_error=None):
        self.clock = clock
        self.cached = cached
        self.read_error = read_error
        self.write_error = write_error
        self.writes = 0

    def get(self, _key):
        self.clock.advance(2)
        if self.read_error is not None:
            raise self.read_error
        return self.cached

    def set(self, _key, value, **_options):
        self.clock.advance(3)
        self.writes += 1
        if self.write_error is not None:
            raise self.write_error
        self.cached = value.encode()
        return b"OK"


@pytest.fixture
def clock(monkeypatch):
    result = Clock()
    monkeypatch.setattr(common.time, "perf_counter_ns", result)
    monkeypatch.setenv("VALKEY_KEY_PREFIX", "cache-latency-test")

    def fetch(_sku):
        result.advance(20)
        return PRODUCT.copy()

    monkeypatch.setattr(cache, "fetch_product", fetch)
    return result


def test_miss_tracks_get_source_set_and_entire_response(clock):
    client = FakeClient(clock)
    timings = cache.CacheLatency()
    assert cache.load_product(client, "speaker", latency=timings) == (PRODUCT, "source")
    assert timings.total_ms == 25
    assert timings.cache_read_ms == 2
    assert timings.source_read_ms == 20
    assert timings.cache_write_ms == 3
    assert timings.cache_read_status == "miss"
    assert timings.cache_write_status == "stored"
    assert client.writes == 1


def test_hit_records_get_and_skips_source_and_write(clock):
    client = FakeClient(clock, cached=json.dumps(PRODUCT).encode())
    timings = cache.CacheLatency()
    assert cache.load_product(client, "speaker", latency=timings) == (PRODUCT, "hit")
    assert timings.total_ms == timings.cache_read_ms == 2
    assert timings.source_read_ms is None
    assert timings.cache_write_ms is None
    assert timings.cache_read_status == "hit"
    assert timings.cache_write_status == "not used"
    assert client.writes == 0


def test_reused_record_does_not_leak_source_timing_into_a_hit(clock):
    client = FakeClient(clock)
    timings = cache.CacheLatency()
    assert cache.load_product(client, "speaker", latency=timings)[1] == "source"
    assert cache.load_product(client, "speaker", latency=timings)[1] == "hit"
    assert timings.total_ms == 2
    assert timings.source_read_ms is None
    assert timings.cache_write_ms is None
    assert timings.cache_write_status == "not used"


@pytest.mark.parametrize("error", [ConnectionError("offline"), TimeoutError("slow")])
def test_transient_read_and_write_failure_preserves_source_and_attempt_times(clock, error):
    client = FakeClient(clock, read_error=error, write_error=error)
    timings = cache.CacheLatency()
    assert cache.load_product(client, "speaker", latency=timings) == (PRODUCT, "source")
    assert timings.total_ms == 25
    assert timings.cache_read_ms == 2
    assert timings.source_read_ms == 20
    assert timings.cache_write_ms == 3
    assert timings.cache_read_status == timings.cache_write_status == "unavailable"
    assert client.writes == 1


def test_failed_cache_write_retains_successful_source_response(clock):
    client = FakeClient(clock, write_error=ConnectionError("offline"))
    timings = cache.CacheLatency()
    assert cache.load_product(client, "speaker", latency=timings) == (PRODUCT, "source")
    assert timings.cache_read_status == "miss"
    assert timings.cache_write_status == "unavailable"
    assert timings.total_ms == 25


def test_authentication_error_is_visible_and_still_records_elapsed_read(clock):
    error = RequestError("invalid credentials")
    client = FakeClient(clock, read_error=error)
    timings = cache.CacheLatency()
    with pytest.raises(RequestError) as raised:
        cache.load_product(client, "speaker", latency=timings)
    assert raised.value is error
    assert timings.total_ms == timings.cache_read_ms == 2
    assert timings.cache_read_status == "failed"
    assert timings.source_read_ms is None
    assert client.writes == 0


def test_malformed_cached_response_is_not_silently_replaced(clock):
    client = FakeClient(clock, cached=b"broken JSON")
    timings = cache.CacheLatency()
    with pytest.raises(json.JSONDecodeError):
        cache.load_product(client, "speaker", latency=timings)
    assert timings.total_ms == timings.cache_read_ms == 2
    assert timings.cache_read_status == "hit"
    assert timings.source_read_ms is None
    assert client.writes == 0


def test_source_error_records_its_time_without_attempting_a_cache_write(clock, monkeypatch):
    def broken_source(_sku):
        clock.advance(20)
        raise RuntimeError("source unavailable")

    monkeypatch.setattr(cache, "fetch_product", broken_source)
    client = FakeClient(clock)
    timings = cache.CacheLatency()
    with pytest.raises(RuntimeError, match="source unavailable"):
        cache.load_product(client, "speaker", latency=timings)
    assert timings.total_ms == 22
    assert timings.source_read_ms == 20
    assert timings.cache_write_ms is None
    assert client.writes == 0


def test_rendered_response_places_payload_and_actual_latency_together(clock, monkeypatch):
    output = StringIO()
    monkeypatch.setattr(cache, "console", Console(file=output, width=200, markup=False))
    timings = cache.CacheLatency()
    product, path = cache.load_product(
        FakeClient(clock, cached=json.dumps(PRODUCT).encode()), "speaker", latency=timings
    )
    cache.print_response("Second request", product, path, timings)
    rendered = output.getvalue()
    assert "Second request: hit; total latency=2.000 ms" in rendered
    assert '"sku": "speaker"' in rendered
    assert "Valkey GET: 2.000 ms (hit)" in rendered
    assert "source read: not used; Valkey SET: not used" in rendered


def test_existing_product_path_pair_is_preserved_without_a_recorder(clock):
    product, path = cache.load_product(FakeClient(clock), "speaker")
    assert product == PRODUCT
    assert path == "source"
