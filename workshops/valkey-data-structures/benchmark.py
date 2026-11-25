"""Compare sequential and pipelined atomic increments on the same workload."""

import math
import statistics
import time

from rich.table import Table

from common import console, key, new_batch, timed
from valkey_client import ValkeyClientManager


def percentile(values: list[float], fraction: float) -> float:
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


def measure(client, counter: str, operations: int, batch_size: int, *, verification_ms=None):
    client.delete([counter])
    samples = []
    started = time.perf_counter()
    for offset in range(0, operations, batch_size):
        size = min(batch_size, operations - offset)
        sample_started = time.perf_counter()
        if batch_size == 1:
            client.incr(counter)
        else:
            pipeline = new_batch(client, is_atomic=False)
            for _ in range(size):
                pipeline.incr(counter)
            client.exec(pipeline, raise_on_error=True)
        samples.append((time.perf_counter() - sample_started) * 1000)
    elapsed = time.perf_counter() - started
    final_count, read_ms = timed(client.get, counter)
    assert int(final_count) == operations
    if verification_ms is not None:
        verification_ms.append(read_ms)
    return elapsed, samples


def main():
    operations = 500
    repeats = 5
    keys = [key("benchmark", "sequential"), key("benchmark", "pipeline")]
    table = Table(title="Same workload · sequential vs GLIDE batch")
    for column in ("Batch", "Increments", "Workload (ms)", "Ops/s", "p50 (ms)", "p95 (ms)", "Samples"):
        table.add_column(column, justify="right")
    with ValkeyClientManager() as client:
        # Establish the connection before taking measurements.
        _, ping_ms = timed(client.ping)
        console.print(f"Valkey PING latency: {ping_ms:.3f} ms")
        try:
            for counter, batch_size in zip(keys, [1, 50]):
                elapsed_runs = []
                samples = []
                verification_ms = []
                for _ in range(repeats):
                    elapsed, run_samples = measure(
                        client, counter, operations, batch_size, verification_ms=verification_ms
                    )
                    elapsed_runs.append(elapsed)
                    samples.extend(run_samples)
                elapsed = statistics.median(elapsed_runs)
                unit = "command" if batch_size == 1 else "batch of 50 commands"
                table.add_row(
                    str(batch_size), str(operations), f"{elapsed * 1000:.2f}",
                    f"{operations / elapsed:.0f}", f"{percentile(samples, .5):.3f}",
                    f"{percentile(samples, .95):.3f}", str(len(samples)),
                )
                console.print(f"Latency unit for batch_size={batch_size}: {unit}")
                console.print(
                    f"Verified 500 increments for batch_size={batch_size}; "
                    f"final GET median latency: {statistics.median(verification_ms):.3f} ms"
                )
        finally:
            _, cleanup_ms = timed(client.delete, keys)
            console.print(f"Benchmark key cleanup latency: {cleanup_ms:.3f} ms")
    console.print(table)
    console.print("Checkpoint: 500 increments per run; both paths agree.")


if __name__ == "__main__":
    main()
