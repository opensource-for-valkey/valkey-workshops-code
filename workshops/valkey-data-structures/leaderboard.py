"""Build a live ranking with a Valkey Sorted Set."""

import math
import random

from glide_sync import RangeByIndex
from rich.table import Table

from common import console, key, text, timed
from valkey_client import ValkeyClientManager


def record_score(client, board, player, score):
    return client.zadd(board, {player: score})


def add_points(client, board, player, points):
    return client.zincrby(board, points, player)


def top_players(client, board, count=10):
    scores = client.zrange_withscores(board, RangeByIndex(0, count - 1), reverse=True)
    return [(text(player), score) for player, score in scores.items()]


def player_rank(client, board, player):
    zero_based = client.zrevrank(board, player)
    return None if zero_based is None else zero_based + 1


def measure(operation, samples=100):
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
    board = key("leaderboard", "conference")
    ties = key("leaderboard", "ties")
    removed, elapsed_ms = timed(client.delete, [board, ties])
    console.print(f"Leaderboard reset: {removed} keys; Valkey DEL latency={elapsed_ms:.3f} ms")
    rng = random.Random(42)
    scores = {f"player{i:05d}": rng.randrange(1000) for i in range(5000)}
    created, elapsed_ms = timed(client.zadd, board, scores)
    console.print(f"Initial scores: {created} players; Valkey ZADD latency={elapsed_ms:.3f} ms")
    updated, elapsed_ms = timed(add_points, client, board, "player00001", 100)
    assert updated == scores["player00001"] + 100
    scores["player00001"] += 100
    console.print(f"player00001 updated score: {updated:g}; Valkey ZINCRBY latency={elapsed_ms:.3f} ms")

    def sorted_baseline():
        # For these ASCII IDs, this matches Valkey's reverse tie ordering.
        return sorted(scores.items(), key=lambda pair: (pair[1], pair[0]),
                      reverse=True)[:10]

    leaders, top_ms = timed(top_players, client, board)
    baseline, sort_ms = timed(sorted_baseline)
    assert leaders == baseline
    console.print(
        f"Top 10 matches: local Python sort latency={sort_ms:.3f} ms; "
        f"Valkey top 10 response latency={top_ms:.3f} ms"
    )
    missing, elapsed_ms = timed(player_rank, client, board, "missing-player")
    assert missing is None
    console.print(f"Missing-player rank: none; Valkey ZREVRANK latency={elapsed_ms:.3f} ms")
    top_three, read_ms = timed(top_players, client, board, 3)
    table = Table(
        title="Conference leaderboard · top 3",
        caption=f"Valkey top 3 response latency={read_ms:.3f} ms",
    )
    table.add_column("Rank", justify="right")
    table.add_column("Player")
    table.add_column("Score", justify="right")
    for rank, (player, score) in enumerate(top_three, 1):
        table.add_row(str(rank), player, f"{score:g}")
    console.print(table)
    rank, elapsed_ms = timed(player_rank, client, board, "player00001")
    console.print(f"player00001 rank (1-based): {rank}; Valkey ZREVRANK latency={elapsed_ms:.3f} ms")
    memory, memory_ms = timed(client.custom_command, ["MEMORY", "USAGE", board])
    count, count_ms = timed(client.zcard, board)
    console.print(
        f"Players: {count}; memory: {memory} bytes; "
        f"Valkey ZCARD latency={count_ms:.3f} ms; MEMORY USAGE latency={memory_ms:.3f} ms"
    )

    created, elapsed_ms = timed(client.zadd, ties, {"alice": 100, "bob": 100, "carol": 90})
    console.print(f"Tie example: {created} players; Valkey ZADD latency={elapsed_ms:.3f} ms")
    ordered, elapsed_ms = timed(client.zrange, ties, RangeByIndex(0, -1), reverse=True)
    assert ordered == [b"bob", b"alice", b"carol"]
    console.print(
        "Tied at 100 (bob before alice in REV), then carol at 90: bob, alice, carol; "
        f"Valkey ZRANGE latency={elapsed_ms:.3f} ms"
    )

    for label, operation in (("Sort 5,000 local records", sorted_baseline),
                             ("Valkey top 10 over TCP", lambda: top_players(client, board))):
        timings = measure(operation)
        console.print(f"{label}: p50={timings[50]:.3f} ms; p95={timings[95]:.3f} ms")
    console.print("The baseline is an in-memory Python sort, not a database benchmark.")
    console.print(f"Inspect board: {board}")


def main():
    with ValkeyClientManager() as client:
        demonstrate(client)


if __name__ == "__main__":
    main()
