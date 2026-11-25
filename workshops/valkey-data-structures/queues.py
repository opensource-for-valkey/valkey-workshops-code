"""A List queue with explicit recovery and measured Valkey command latency."""

import argparse
import json
import re
from uuid import uuid4

from glide_sync import ListDirection
from rich.table import Table

from common import LatencyTimer, console, key, scan_keys, text, timed
from valkey_client import ValkeyClientManager


def processing_key(worker: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", worker):
        raise ValueError("Worker IDs must contain 1-32 letters, digits, underscores, or hyphens.")
    return key("queue", "processing", worker)


def enqueue(count: int = 3) -> None:
    if not 1 <= count <= 20:
        raise ValueError("Choose between 1 and 20 jobs.")
    jobs = [
        json.dumps({"job_id": str(uuid4()), "report": f"daily-report-{number}"})
        for number in range(1, count + 1)
    ]
    with ValkeyClientManager() as client:
        _, push_ms = timed(client.lpush, key("queue", "ready"), jobs)
    console.print(
        f"Enqueued {count} unique jobs; Valkey LPUSH: {push_ms:.3f} ms. "
        "LPUSH + a RIGHT-side claim gives FIFO."
    )


def work(worker: str, crash_after_claim: bool = False, crash_after_effect: bool = False) -> None:
    processing = processing_key(worker)
    with ValkeyClientManager() as client:
        unfinished, check_ms = timed(client.llen, processing)
        if unfinished:
            raise RuntimeError(
                f"{worker} has unfinished jobs; Valkey LLEN: {check_ms:.3f} ms. "
                "Stop its process and recover them first."
            )
        console.print(f"{worker} owns 0 pending jobs; Valkey LLEN: {check_ms:.3f} ms")
        while True:
            # The measured BLMOVE duration includes waiting for a job, up to 2 seconds.
            # This block is below the shared client's 5-second request timeout.
            raw, claim_ms = timed(
                client.blmove, key("queue", "ready"), processing,
                ListDirection.RIGHT, ListDirection.LEFT, 2,
            )
            if raw is None:
                console.print(
                    f"No ready jobs after 2 seconds; Valkey BLMOVE (including wait): "
                    f"{claim_ms:.3f} ms; worker exiting."
                )
                return
            job = json.loads(raw)
            console.print(
                f"CLAIMED {job['job_id']} ({job['report']}) by {worker}; "
                f"Valkey BLMOVE (including wait): {claim_ms:.3f} ms"
            )
            if crash_after_claim:
                console.print("SIMULATED CRASH before the effect. The job remains in processing.")
                raise SystemExit(2)

            # HSETNX is the entire toy effect; external effects need durable idempotency.
            first_attempt, effect_ms = timed(
                client.hsetnx, key("queue", "results"),
                job["job_id"], f"Generated {job['report']}"
            )
            effect = "Created result." if first_attempt else "Result already exists; duplicate effect skipped."
            console.print(f"{effect} Valkey HSETNX effect: {effect_ms:.3f} ms")
            if crash_after_effect:
                console.print("SIMULATED CRASH after the effect, before acknowledgement.")
                raise SystemExit(2)
            acknowledged, acknowledge_ms = timed(client.lrem, processing, 1, raw)
            if acknowledged != 1:
                raise RuntimeError(
                    f"Job ownership changed; Valkey LREM: {acknowledge_ms:.3f} ms. "
                    "Stop and inspect before processing more jobs."
                )
            console.print(
                f"ACKNOWLEDGED {job['job_id']}; Valkey LREM: {acknowledge_ms:.3f} ms"
            )


def recover(worker: str, stopped: bool = False) -> None:
    processing = processing_key(worker)
    if not stopped:
        raise ValueError("Stop the worker process first, then repeat with --stopped.")
    recovered = []
    with ValkeyClientManager() as client:
        with LatencyTimer() as recovery:
            while True:
                raw, move_ms = timed(
                    client.lmove, processing, key("queue", "ready"),
                    ListDirection.RIGHT, ListDirection.LEFT,
                )
                if raw is None:
                    empty_ms = move_ms
                    break
                recovered.append(move_ms)
    for number, move_ms in enumerate(recovered, 1):
        console.print(f"REQUEUED entry {number}; Valkey LMOVE: {move_ms:.3f} ms")
    console.print(
        f"Requeued {len(recovered)} job(s) belonging to stopped worker {worker}; "
        f"recovery loop: {recovery.elapsed_ms:.3f} ms; "
        f"final empty Valkey LMOVE: {empty_ms:.3f} ms"
    )


def inspect() -> None:
    rows = []
    with ValkeyClientManager() as client:
        with LatencyTimer() as inspection:
            ready, ready_ms = timed(client.llen, key("queue", "ready"))
            results, results_ms = timed(client.hlen, key("queue", "results"))
            pending, scan_ms = timed(
                lambda: sorted(scan_keys(client, key("queue", "processing", "*")))
            )
            for processing in pending:
                count, count_ms = timed(client.llen, processing)
                entries, entries_ms = timed(client.lrange, processing, 0, -1)
                for raw in entries:
                    rows.append((text(processing), str(count), json.loads(raw)["job_id"],
                                 f"{count_ms:.3f}", f"{entries_ms:.3f}"))
    console.print(f"Ready jobs: {ready}; Valkey LLEN: {ready_ms:.3f} ms")
    console.print(f"Toy results: {results}; Valkey HLEN: {results_ms:.3f} ms")
    console.print(
        f"Processing keys: {len(pending)}; Valkey SCAN + local sort: {scan_ms:.3f} ms"
    )
    table = Table(title="Worker ownership · processing lists")
    for column in ("Processing key", "Pending", "Job ID", "LLEN (ms)", "LRANGE (ms)"):
        table.add_column(column, justify="right" if column in {"Pending", "LLEN (ms)", "LRANGE (ms)"} else "left")
    for row in rows:
        table.add_row(*row)
    console.print(table)
    console.print(f"Inspection reads and decoding: {inspection.elapsed_ms:.3f} ms")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    producer = actions.add_parser("enqueue")
    producer.add_argument("--count", type=int, default=3)
    worker = actions.add_parser("work")
    worker.add_argument("--worker", required=True)
    failure = worker.add_mutually_exclusive_group()
    failure.add_argument("--crash-after-claim", action="store_true")
    failure.add_argument("--crash-after-effect", action="store_true")
    recovery = actions.add_parser("recover")
    recovery.add_argument("--worker", required=True)
    recovery.add_argument("--stopped", action="store_true")
    actions.add_parser("inspect")
    args = parser.parse_args()
    try:
        if args.action == "enqueue":
            enqueue(args.count)
        elif args.action == "work":
            work(args.worker, args.crash_after_claim, args.crash_after_effect)
        elif args.action == "recover":
            recover(args.worker, args.stopped)
        else:
            inspect()
    except KeyboardInterrupt:
        console.print("\nWorker stopped. Inspect its processing list before restarting.")
    except (ValueError, RuntimeError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
