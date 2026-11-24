"""Small, inspectable movie Search and recommendation workload using GLIDE."""

from __future__ import annotations

import time
from collections.abc import Mapping

import numpy as np
from glide_sync import Batch, RequestError
from rich.console import Console
from rich.table import Table

from valkey_client_manager import ValkeyClientManager, search_document_keys

INDEX = "workshop_movies_v1"
PREFIX = "workshop:movies:v1:"
MOVIES = (
    ("1", "Orbit Rescue", "science-fiction", 2025, 98, [1, 0, 0]),
    ("2", "Lunar Station", "science-fiction", 2024, 82, [0.95, 0.05, 0]),
    ("3", "Harbour Mystery", "mystery", 2023, 76, [0, 1, 0]),
    ("4", "City Laughs", "comedy", 2025, 91, [0, 0, 1]),
)


def prepare(client) -> None:
    try:
        client.custom_command(["FT.INFO", INDEX])
    except RequestError:
        client.custom_command(
            [
                "FT.CREATE",
                INDEX,
                "ON",
                "HASH",
                "PREFIX",
                "1",
                PREFIX,
                "SCHEMA",
                "title",
                "TEXT",
                "genre",
                "TAG",
                "year",
                "NUMERIC",
                "SORTABLE",
                "popularity",
                "NUMERIC",
                "SORTABLE",
                "embedding",
                "VECTOR",
                "HNSW",
                "6",
                "TYPE",
                "FLOAT32",
                "DIM",
                "3",
                "DISTANCE_METRIC",
                "COSINE",
            ]
        )
    batch = Batch(is_atomic=True)
    for movie_id, title, genre, year, popularity, vector in MOVIES:
        batch.hset(
            PREFIX + movie_id,
            {
                "title": title,
                "genre": genre,
                "year": str(year),
                "popularity": str(popularity),
                "embedding": np.asarray(vector, dtype=np.float32).tobytes(),
            },
        )
    client.exec(batch, raise_on_error=True)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.custom_command(["FT.SEARCH", INDEX, "*", "NOCONTENT"])
        if response and int(response[0]) == len(MOVIES):
            return
        time.sleep(0.1)
    raise RuntimeError("Search index did not finish indexing within five seconds")


def document_keys(response) -> list[bytes]:
    if not response or int(response[0]) == 0:
        return []
    if not isinstance(response[1], Mapping):
        raise TypeError("Expected the Valkey Search document mapping")
    return list(response[1])


def display(client, keys: list[bytes], title: str) -> None:
    table = Table(title=title)
    for heading in ("Title", "Genre", "Year", "Popularity"):
        table.add_column(heading)
    for key in keys:
        fields = client.hmget(key, ["title", "genre", "year", "popularity"])
        table.add_row(*(value.decode() if value else "" for value in fields))
    Console().print(table)


def main() -> None:
    with ValkeyClientManager(default_port=16379) as manager:
        client = manager.client
        prepare(client)
        display(
            client,
            document_keys(
                client.custom_command(["FT.SEARCH", INDEX, "orbit", "NOCONTENT"])
            ),
            "Instant title search",
        )
        display(
            client,
            document_keys(
                client.custom_command(["FT.SEARCH", INDEX, "@title:(Lu*)", "NOCONTENT"])
            ),
            "Title suggestions",
        )
        vector = np.asarray([1, 0, 0], dtype=np.float32).tobytes()
        keys = search_document_keys(client, INDEX, vector, 3)
        display(
            client,
            [key for key in keys if key != (PREFIX + "1").encode()],
            "Because you watched Orbit Rescue",
        )
        display(
            client,
            document_keys(
                client.custom_command(
                    [
                        "FT.SEARCH",
                        INDEX,
                        "*",
                        "NOCONTENT",
                        "SORTBY",
                        "popularity",
                        "DESC",
                        "LIMIT",
                        "0",
                        "3",
                    ]
                )
            ),
            "Trending movies",
        )


if __name__ == "__main__":
    main()
