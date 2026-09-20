"""Regression tests for reliable, portable write-behind processing."""

import json
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest
from sqlalchemy.dialects import mysql, postgresql

from daos.write_behind_cache import WriteBehindCache


class FakePipeline:
    def __init__(self, client):
        self.client = client
        self.operations = []

    def __getattr__(self, name):
        def queue_operation(*args):
            self.operations.append((name, args))
            return self

        return queue_operation

    def execute(self):
        if self.client.fail_next_pipeline:
            self.client.fail_next_pipeline = False
            raise ConnectionError("pipeline unavailable")
        return [getattr(self.client, name)(*args) for name, args in self.operations]


class FakeValkey:
    def __init__(self):
        self.values = {}
        self.lists = defaultdict(list)
        self.fail_next_pipeline = False

    def pipeline(self, transaction=True):
        assert transaction
        return FakePipeline(self)

    def get(self, key):
        return self.values.get(key)

    def setex(self, key, ttl, value):
        self.values[key] = value
        return True

    def rpush(self, key, value):
        self.lists[key].append(value)
        return len(self.lists[key])

    def lpush(self, key, value):
        self.lists[key].insert(0, value)
        return len(self.lists[key])

    def llen(self, key):
        return len(self.lists[key])

    def lmove(self, source, destination, wherefrom, whereto):
        if not self.lists[source]:
            return None
        value = (
            self.lists[source].pop(0)
            if wherefrom.upper() == "LEFT"
            else self.lists[source].pop()
        )
        if whereto.upper() == "LEFT":
            self.lists[destination].insert(0, value)
        else:
            self.lists[destination].append(value)
        return value

    def lrem(self, key, count, value):
        assert count == 1
        try:
            self.lists[key].remove(value)
            return 1
        except ValueError:
            return 0

    def delete(self, key):
        return int(self.values.pop(key, None) is not None)

    def close(self):
        return None


class FakeCache:
    cache_type = "valkey"

    def __init__(self):
        self.client = FakeValkey()

    def get(self, key):
        return self.client.get(key)

    def set(self, key, value, ttl=None):
        return self.client.setex(key, ttl, value)

    def close(self):
        return None


class FakeRow:
    def __init__(self, values):
        self._mapping = values


class FakeResult:
    def __init__(self, row=None):
        self.row = FakeRow(row) if row is not None else None

    def fetchone(self):
        return self.row


class FakeConnection:
    def __init__(self, engine):
        self.engine = engine

    def execute(self, statement, parameters=None):
        sql = str(statement).strip()
        parameters = parameters or {}
        self.engine.queries.append((sql, parameters))
        if sql.startswith("SELECT"):
            return FakeResult(self.engine.row)
        if sql.startswith("UPDATE"):
            if self.engine.fail_update:
                raise RuntimeError("database unavailable")
            self.engine.row["departure"] = parameters["new_departure"]
            self.engine.row["arrival"] = parameters["new_arrival"]
        if sql.startswith("INSERT"):
            self.engine.logs.append(parameters)
        return FakeResult()


class FakeEngine:
    def __init__(self, dialect, row=None, fail_update=False):
        self.dialect = dialect
        self.row = row
        self.fail_update = fail_update
        self.queries = []
        self.logs = []

    @contextmanager
    def connect(self):
        yield FakeConnection(self)

    @contextmanager
    def begin(self):
        yield FakeConnection(self)

    def dispose(self):
        return None


def flight_row(now):
    return {
        "flight_id": 115,
        "flightno": "VK115",
        "departure": now,
        "arrival": now + timedelta(hours=2),
        "airline_id": 1,
        "airplane_id": 2,
        "from_id": 3,
        "to_id": 4,
        "from_airport": "SEA",
        "to_airport": "SFO",
        "airlinename": "Valkey Air",
    }


def seed_cached_flight(cache, row):
    serializable = {
        key: value.isoformat() if isinstance(value, datetime) else value
        for key, value in row.items()
    }
    cache.client.values["flight:115"] = json.dumps(serializable)


def test_publication_is_atomic_and_propagates_failure():
    now = datetime(2026, 7, 17, 10, 0)
    cache = FakeCache()
    row = flight_row(now)
    seed_cached_flight(cache, row)
    original = cache.client.values["flight:115"]
    cache.client.fail_next_pipeline = True
    handler = WriteBehindCache(FakeEngine(postgresql.dialect(), row), cache)

    with pytest.raises(ConnectionError, match="pipeline unavailable"):
        handler.update_flight_departure(
            115, now + timedelta(hours=1), now + timedelta(hours=3)
        )

    assert cache.client.values["flight:115"] == original
    assert handler.get_queue_length() == 0


@pytest.mark.parametrize(
    ("dialect", "quoted_from", "quoted_user"),
    [
        (postgresql.dialect(), '"from"', '"user"'),
        (mysql.dialect(), "`from`", "`user`"),
    ],
)
def test_processing_commits_then_acknowledges_with_portable_sql(
    dialect, quoted_from, quoted_user
):
    now = datetime(2026, 7, 17, 10, 0)
    row = flight_row(now)
    cache = FakeCache()
    seed_cached_flight(cache, row)
    engine = FakeEngine(dialect, row)
    handler = WriteBehindCache(engine, cache)

    assert handler.update_flight_departure(
        115, now + timedelta(hours=1), now + timedelta(hours=3), user="instructor"
    )[0]
    processed, failed, queries = handler.process_queue()

    assert (processed, failed) == (1, 0)
    assert handler.get_queue_length() == 0
    assert len(engine.logs) == 1
    rendered_sql = "\n".join(queries)
    assert quoted_from in rendered_sql
    assert quoted_user in rendered_sql
    assert "NOW()" not in rendered_sql
    assert engine.logs[0]["log_date"].tzinfo is not None


def test_database_failures_retry_then_dead_letter_without_task_loss():
    now = datetime(2026, 7, 17, 10, 0)
    row = flight_row(now)
    cache = FakeCache()
    seed_cached_flight(cache, row)
    handler = WriteBehindCache(
        FakeEngine(postgresql.dialect(), row, fail_update=True),
        cache,
        max_retries=2,
    )
    handler.update_flight_departure(
        115, now + timedelta(hours=1), now + timedelta(hours=3)
    )

    processed, failed, _ = handler.process_queue(batch_size=2)

    assert (processed, failed) == (0, 2)
    assert handler.get_queue_length() == 0
    assert handler.get_dead_letter_length() == 1
    dead_task = json.loads(cache.client.lists[handler.DEAD_LETTER_KEY][0])
    assert dead_task["attempts"] == 2
    assert "database unavailable" in dead_task["last_error"]
    assert "flight:115" not in cache.client.values


def test_abandoned_processing_task_is_recovered():
    cache = FakeCache()
    handler = WriteBehindCache(
        FakeEngine(postgresql.dialect(), flight_row(datetime.now())), cache
    )
    cache.client.lists[handler.PROCESSING_KEY].append('{"id": "abandoned"}')

    assert handler.recover_processing_tasks() == 1
    assert cache.client.lists[handler.PROCESSING_KEY] == []
    assert cache.client.lists[handler.QUEUE_KEY] == ['{"id": "abandoned"}']


def test_malformed_task_is_dead_lettered():
    cache = FakeCache()
    handler = WriteBehindCache(
        FakeEngine(postgresql.dialect(), flight_row(datetime.now())),
        cache,
        max_retries=1,
    )
    cache.client.lists[handler.QUEUE_KEY].append("not-json")

    processed, failed, _ = handler.process_queue(batch_size=1)

    assert (processed, failed) == (0, 1)
    assert handler.get_dead_letter_length() == 1
    dead_task = json.loads(cache.client.lists[handler.DEAD_LETTER_KEY][0])
    assert dead_task["raw_task"] == "not-json"



def test_retry_remains_ahead_of_newer_updates():
    now = datetime(2026, 7, 17, 10, 0)
    row = flight_row(now)
    cache = FakeCache()
    seed_cached_flight(cache, row)
    handler = WriteBehindCache(
        FakeEngine(postgresql.dialect(), row, fail_update=True),
        cache,
        max_retries=3,
    )
    handler.update_flight_departure(
        115, now + timedelta(hours=1), now + timedelta(hours=3)
    )
    handler.update_flight_departure(
        115, now + timedelta(hours=2), now + timedelta(hours=4)
    )
    original_ids = [
        json.loads(task)["id"] for task in cache.client.lists[handler.QUEUE_KEY]
    ]

    handler.process_queue(batch_size=1)

    retry_ids = [
        json.loads(task)["id"] for task in cache.client.lists[handler.QUEUE_KEY]
    ]
    assert retry_ids == original_ids
