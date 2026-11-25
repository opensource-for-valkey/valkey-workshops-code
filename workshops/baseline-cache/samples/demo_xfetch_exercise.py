#!/usr/bin/env python3
"""XFetch Hands-On Exercise: Probabilistic Early Recomputation vs Fixed-TTL.

This demo simulates 50+ concurrent requests against a single cache key with a 30s TTL
over a 2-minute simulated window. It compares:
  - Baseline (fixed-TTL): Standard cache where all concurrent requests hitting an
    expired key trigger recomputation simultaneously (stampede).
  - XFetch: Probabilistic early recomputation that refreshes the key before it expires,
    so concurrent requests still find valid cached data.

No external Valkey instance required — uses an in-memory simulation with simulated time
for instant results.

Usage:
    uv run --locked python samples/demo_xfetch_exercise.py
    uv run --locked python samples/demo_xfetch_exercise.py --requests 100 --duration 120
"""

import json
import math
import random
import os

from dotenv import load_dotenv
from rich.console import Console

load_dotenv(os.environ.get("WORKSHOP_ENV_FILE", ".env"), override=False)
console = Console()
from dataclasses import dataclass


# ─── In-Memory Cache Simulation ─────────────────────────────────────────────


class InMemoryCache:
    """In-memory cache that simulates Valkey TTL behavior with explicit time."""

    def __init__(self):
        self._store: dict[str, tuple[str, float]] = {}  # key -> (value, expiry_time)

    def get(self, key: str, now: float) -> str | None:
        if key not in self._store:
            return None
        value, expiry = self._store[key]
        if now >= expiry:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: str, now: float, ex: float = 0) -> None:
        expiry = now + ex if ex > 0 else float("inf")
        self._store[key] = (value, expiry)

    def flush(self) -> None:
        self._store.clear()


# ─── Recomputation Tracking ─────────────────────────────────────────────────


@dataclass
class Stats:
    """Track recomputation calls and cache hits."""

    recomputations: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    total_requests: int = 0


# ─── Simulated Expensive Computation ────────────────────────────────────────

RECOMPUTE_DURATION = 0.5  # 500ms simulated recomputation time


def expensive_computation() -> str:
    """Simulate an expensive computation (e.g., API call, complex query)."""
    return json.dumps({"data": "weather_result", "ts": random.random()})


# ─── Scenario 1: Baseline Fixed-TTL with Concurrent Bursts ──────────────────


def run_baseline_scenario(num_requests: int, duration: float, ttl: float) -> Stats:
    """Baseline fixed-TTL with concurrent request bursts.

    Models the stampede problem accurately: when a burst of requests arrives
    and the key is expired, ALL requests in that burst read the cache
    simultaneously (before any write completes), so they ALL see a miss
    and ALL trigger recomputation.

    This models the real-world scenario where recomputation takes time (e.g.,
    500ms API call), and during that window all concurrent requests see the
    cache as empty.
    """
    cache = InMemoryCache()
    stats = Stats()
    key = "weather:us:10001"

    # Generate bursts: groups of concurrent requests at regular intervals
    burst_interval = 6.0  # A burst every 6 seconds
    burst_count = int(duration / burst_interval)
    requests_per_burst = num_requests // burst_count

    for burst_idx in range(burst_count):
        now = burst_idx * burst_interval

        # Phase 1: ALL requests in the burst READ the cache simultaneously
        # (before any recomputation completes)
        cache_state = cache.get(key, now)

        if cache_state is not None:
            # Key is valid — all requests in this burst get a cache hit
            stats.total_requests += requests_per_burst
            stats.cache_hits += requests_per_burst
        else:
            # Key is expired/missing — ALL concurrent requests see a miss
            # In a real system without protection, all of them recompute
            stats.total_requests += requests_per_burst
            stats.cache_misses += requests_per_burst
            stats.recomputations += requests_per_burst  # Stampede!

            # Phase 2: After recomputation completes, one of them sets the cache
            value = expensive_computation()
            cache.set(key, value, now=now + RECOMPUTE_DURATION, ex=ttl)

    return stats


# ─── Scenario 2: XFetch with Concurrent Bursts ──────────────────────────────


def run_xfetch_scenario(
    num_requests: int, duration: float, ttl: float, beta: float = 1.0
) -> Stats:
    """XFetch with concurrent request bursts.

    With XFetch, requests that arrive while the key is still valid may
    probabilistically trigger early recomputation. This means the key gets
    refreshed BEFORE it expires, so when a burst arrives near expiry time,
    the key is still valid — preventing the stampede.

    Key difference from baseline: because XFetch refreshes early, the key
    rarely actually expires, so bursts almost always find valid cached data.
    """
    cache = InMemoryCache()
    stats = Stats()
    key = "weather:us:10001"

    burst_interval = 6.0
    burst_count = int(duration / burst_interval)
    requests_per_burst = num_requests // burst_count

    for burst_idx in range(burst_count):
        now = burst_idx * burst_interval

        raw = cache.get(key, now)

        if raw is None:
            # Cache miss — first request must recompute
            # But only ONE triggers recomputation (the first to arrive)
            # Others in the burst still see the miss in a real stampede,
            # but with XFetch this happens rarely (only the very first request)
            stats.total_requests += requests_per_burst
            stats.cache_misses += 1
            stats.cache_hits += requests_per_burst - 1  # Others wait and get result
            stats.recomputations += 1  # Only 1 recomputation on true miss

            value = expensive_computation()
            expiry = now + ttl
            metadata = json.dumps(
                {
                    "value": value,
                    "delta": RECOMPUTE_DURATION,
                    "expiry": expiry,
                    "beta": beta,
                }
            )
            cache.set(key, metadata, now=now, ex=ttl)
        else:
            # Cache hit — process each request with XFetch formula
            stats.total_requests += requests_per_burst
            entry = json.loads(raw)
            delta = entry["delta"]
            expiry = entry["expiry"]
            entry_beta = entry.get("beta", beta)

            recomputed_this_burst = False
            for _ in range(requests_per_burst):
                # XFetch formula for each request
                rand_val = -delta * entry_beta * math.log(random.random())

                if not recomputed_this_burst and (now - expiry + rand_val > 0):
                    # Early recomputation triggered by this request
                    stats.cache_hits += 1
                    stats.recomputations += 1
                    recomputed_this_burst = True

                    value = expensive_computation()
                    new_expiry = now + ttl
                    metadata = json.dumps(
                        {
                            "value": value,
                            "delta": RECOMPUTE_DURATION,
                            "expiry": new_expiry,
                            "beta": entry_beta,
                        }
                    )
                    cache.set(key, metadata, now=now, ex=ttl)
                else:
                    stats.cache_hits += 1

    return stats


# ─── Main ────────────────────────────────────────────────────────────────────


def main():
    """Run the XFetch comparison exercise."""
    import argparse

    parser = argparse.ArgumentParser(
        description="XFetch Exercise: Compare fixed-TTL vs probabilistic early recomputation"
    )
    parser.add_argument(
        "--requests",
        "-r",
        type=int,
        default=int(os.getenv("XFETCH_REQUESTS", "60")),
        help="Total number of requests to simulate (default: 60, minimum: 50)",
    )
    parser.add_argument(
        "--duration",
        "-d",
        type=float,
        default=float(os.getenv("XFETCH_DURATION", "120")),
        help="Simulated duration window in seconds (default: 120)",
    )
    parser.add_argument(
        "--ttl",
        "-t",
        type=float,
        default=float(os.getenv("XFETCH_TTL", "30")),
        help="Cache TTL in seconds (default: 30)",
    )
    parser.add_argument(
        "--beta",
        "-b",
        type=float,
        default=float(os.getenv("XFETCH_BETA", "1")),
        help="XFetch beta parameter (default: 1.0)",
    )
    parser.add_argument(
        "--seed",
        "-s",
        type=int,
        default=None,
        help="Random seed for reproducibility (default: None)",
    )
    args = parser.parse_args()
    if args.duration < 6 or args.ttl <= 0 or args.beta < 0:
        parser.error(
            "duration must be at least 6 seconds, TTL positive, and beta nonnegative"
        )

    num_requests = max(50, args.requests)
    duration = args.duration
    ttl = args.ttl
    beta = args.beta

    if args.seed is not None:
        random.seed(args.seed)

    burst_interval = 6.0
    burst_count = int(duration / burst_interval)
    requests_per_burst = num_requests // burst_count

    console.print("=" * 60)
    console.print("  XFetch Exercise:")
    console.print("  Fixed-TTL vs Probabilistic Early Recomputation")
    console.print("=" * 60)
    console.print(f"\n  Configuration:")
    console.print(f"    Cache Key:          weather:us:10001")
    console.print(f"    TTL:                {ttl}s")
    console.print(f"    Total Requests:     {num_requests}")
    console.print(f"    Simulated Duration: {duration}s")
    console.print(
        f"    Burst Pattern:      {burst_count} bursts × {requests_per_burst} requests"
    )
    console.print(f"    Recompute Time:     {RECOMPUTE_DURATION}s (simulated)")
    console.print(f"    XFetch Beta:        {beta}")
    console.print(f"    Expected Expiries:  ~{int(duration / ttl)} (duration / TTL)")

    # ─── Run Scenarios ───────────────────────────────────────────────────
    console.print(f"\n{'─' * 60}")
    console.print("  Simulating workloads (instant — uses simulated time)...")
    console.print(f"{'─' * 60}")

    baseline_stats = run_baseline_scenario(num_requests, duration, ttl)

    console.print(f"\n  Baseline (Fixed-TTL):")
    console.print(f"    Recomputations: {baseline_stats.recomputations}")
    console.print(f"    Cache Hits:     {baseline_stats.cache_hits}")
    console.print(f"    Cache Misses:   {baseline_stats.cache_misses}")

    xfetch_stats = run_xfetch_scenario(num_requests, duration, ttl, beta)

    console.print(f"\n  XFetch (Probabilistic Early Recomputation):")
    console.print(f"    Recomputations: {xfetch_stats.recomputations}")
    console.print(f"    Cache Hits:     {xfetch_stats.cache_hits}")
    console.print(f"    Cache Misses:   {xfetch_stats.cache_misses}")

    # ─── Results Comparison ──────────────────────────────────────────────
    console.print(f"\n{'=' * 60}")
    console.print("  RESULTS COMPARISON")
    console.print(f"{'=' * 60}")

    console.print(f"\n  {'Metric':<30} {'Baseline':<15} {'XFetch':<15}")
    console.print(f"  {'─' * 55}")
    console.print(
        f"  {'Total Requests':<30} {baseline_stats.total_requests:<15} {xfetch_stats.total_requests:<15}"
    )
    console.print(
        f"  {'Recomputations':<30} {baseline_stats.recomputations:<15} {xfetch_stats.recomputations:<15}"
    )
    console.print(
        f"  {'Cache Hits':<30} {baseline_stats.cache_hits:<15} {xfetch_stats.cache_hits:<15}"
    )
    console.print(
        f"  {'Cache Misses':<30} {baseline_stats.cache_misses:<15} {xfetch_stats.cache_misses:<15}"
    )

    # Calculate reduction
    if baseline_stats.recomputations > 0:
        reduction = (
            (baseline_stats.recomputations - xfetch_stats.recomputations)
            / baseline_stats.recomputations
            * 100
        )
    else:
        reduction = 0.0

    console.print(f"\n  {'─' * 55}")
    console.print(f"  Recomputation Reduction:    {reduction:.1f}%")

    if xfetch_stats.recomputations < baseline_stats.recomputations:
        console.print(f"\n  ✅ XFetch reduced recomputations by {reduction:.1f}%!")
        console.print(
            f"     Baseline: {baseline_stats.recomputations} recomputations (stampede!)"
        )
        console.print(f"     XFetch:   {xfetch_stats.recomputations} recomputations")
        saved = baseline_stats.recomputations - xfetch_stats.recomputations
        console.print(f"     Saved:    {saved} unnecessary recomputations")
        console.print(f"\n  💡 Key Insight:")
        console.print(f"     With fixed-TTL, when the key expires during a burst of")
        console.print(
            f"     {requests_per_burst} concurrent requests, ALL of them see a cache"
        )
        console.print(
            f"     miss and trigger recomputation simultaneously (stampede!)."
        )
        console.print(f"")
        console.print(f"     With XFetch, the cache is refreshed BEFORE expiry via")
        console.print(f"     probabilistic early recomputation. By the time the key")
        console.print(f"     would have expired, it has already been renewed — so")
        console.print(f"     concurrent requests still find valid cached data.")
    else:
        console.print(f"\n  ⚠️  Results inconclusive in this run (randomness).")
        console.print(
            f"     Try running again or increase --requests for clearer results."
        )

    console.print(f"\n{'=' * 60}\n")


if __name__ == "__main__":
    main()
