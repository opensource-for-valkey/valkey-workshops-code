"""Regression tests for write-through transaction boundaries."""

from datetime import datetime, timezone

from sqlalchemy.dialects import postgresql

from daos.write_through_cache import WriteThroughCache


class FakeRow:
    _mapping = {
        "flight_id": 1,
        "flightno": "VK101",
        "from_id": 10,
        "to_id": 20,
        "departure": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "arrival": datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
        "airline_id": 30,
        "airplane_id": 40,
    }


class FakeResult:
    def fetchone(self):
        return FakeRow()


class FakeConnection:
    def __init__(self, events, queries):
        self.events = events
        self.queries = queries

    def execute(self, query, parameters):
        self.events.append("sql")
        self.queries.append(str(query))
        return FakeResult()


class FakeTransaction:
    def __init__(self, events, queries):
        self.events = events
        self.connection = FakeConnection(events, queries)

    def __enter__(self):
        self.events.append("begin")
        return self.connection

    def __exit__(self, exc_type, exc_value, traceback):
        self.events.append("rollback" if exc_type else "commit")
        return False


class FakeEngine:
    def __init__(self, events):
        self.events = events
        self.queries = []
        self.dialect = postgresql.dialect()

    def begin(self):
        return FakeTransaction(self.events, self.queries)


class FailingInvalidationCache:
    def delete(self, key):
        raise ConnectionError("cache unavailable")


class RecordingCache:
    def __init__(self, events):
        self.events = events

    def delete(self, key):
        self.events.append("delete")
        return True


def test_cache_invalidation_failure_rolls_back_database_update():
    events = []
    write_through = WriteThroughCache.__new__(WriteThroughCache)
    write_through.db_engine = FakeEngine(events)
    write_through.cache = FailingInvalidationCache()
    write_through.default_ttl = 3600

    success, _ = write_through.update_flight_departure(
        1,
        datetime(2026, 1, 2, tzinfo=timezone.utc),
        datetime(2026, 1, 2, 1, tzinfo=timezone.utc),
    )

    assert not success
    assert events[-1] == "rollback"
    assert "commit" not in events


def test_cache_is_invalidated_again_after_database_commit():
    events = []
    write_through = WriteThroughCache.__new__(WriteThroughCache)
    write_through.db_engine = FakeEngine(events)
    write_through.cache = RecordingCache(events)
    write_through.default_ttl = 3600
    write_through._cache_sync_required = set()
    write_through.get_flight = lambda flight_id: events.append("warm")

    success, _ = write_through.update_flight_departure(
        1,
        datetime(2026, 1, 2, tzinfo=timezone.utc),
        datetime(2026, 1, 2, 1, tzinfo=timezone.utc),
    )

    assert success
    assert events.count("delete") == 2
    assert events.index("delete") < events.index("commit")
    assert events.index("commit") < len(events) - 2
    assert events[-2:] == ["delete", "warm"]


def test_update_queries_quote_reserved_identifiers_for_postgresql():
    events = []
    engine = FakeEngine(events)
    write_through = WriteThroughCache.__new__(WriteThroughCache)
    write_through.db_engine = engine
    write_through.cache = RecordingCache(events)
    write_through.default_ttl = 3600
    write_through._cache_sync_required = set()
    write_through.get_flight = lambda flight_id: None

    success, queries = write_through.update_flight_departure(
        1,
        datetime(2026, 1, 2, tzinfo=timezone.utc),
        datetime(2026, 1, 2, 1, tzinfo=timezone.utc),
    )

    assert success
    rendered_sql = "\n".join(queries)
    assert '"from"' in rendered_sql
    assert '"to"' in rendered_sql
    assert '"user"' in rendered_sql
    assert "NOW()" not in rendered_sql
