"""
Write-behind cache pattern implementation.

Updates are published atomically to Valkey and processed with at-least-once
semantics. A task remains in a processing list until its database transaction
commits, and bounded retries route poison tasks to a dead-letter list.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import Engine

# Add parent directory to path when running as a script.
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent))

from core import get_cache_client, get_db_engine, quote_identifier


class WriteBehindCache:
    """Write-behind cache implementation for flight data."""

    QUEUE_KEY = "flight_updates_queue"
    PROCESSING_KEY = "flight_updates_processing"
    DEAD_LETTER_KEY = "flight_updates_dead_letter"

    def __init__(
        self,
        db_engine: Optional[Engine] = None,
        cache: Optional[Any] = None,
        max_retries: Optional[int] = None,
    ):
        """Initialize injectable database and transactional cache connections."""
        self.db_engine = db_engine or get_db_engine()
        self.cache = cache or get_cache_client()
        self.default_ttl = int(os.getenv("CACHE_TTL", "3600"))
        self.max_retries = max_retries or int(
            os.getenv("WRITE_BEHIND_MAX_RETRIES", "3")
        )

        cache_type = getattr(self.cache, "cache_type", "valkey").lower()
        if cache_type not in {"redis", "valkey"}:
            raise ValueError(
                "WriteBehindCache requires Redis or Valkey for transactions and lists"
            )
        if self.max_retries < 1:
            raise ValueError("WRITE_BEHIND_MAX_RETRIES must be at least 1")

    def _generate_cache_key(self, entity_type: str, entity_id: int) -> str:
        """Generate a cache key for an entity."""
        return f"{entity_type}:{entity_id}"

    def _quote_identifier(self, identifier: str) -> str:
        """Quote a SQL identifier for the configured database dialect."""
        return quote_identifier(self.db_engine, identifier)

    def _flight_query(self) -> str:
        """Build the shared flight query with portable reserved identifiers."""
        from_column = self._quote_identifier("from")
        to_column = self._quote_identifier("to")
        return f"""
            SELECT
                f.flight_id,
                f.flightno,
                f.departure,
                f.arrival,
                f.airline_id,
                f.airplane_id,
                dep.iata AS from_airport,
                arr.iata AS to_airport,
                al.airlinename
            FROM flight f
            JOIN airport dep ON f.{from_column} = dep.airport_id
            JOIN airport arr ON f.{to_column} = arr.airport_id
            JOIN airline al ON f.airline_id = al.airline_id
            WHERE f.flight_id = :flight_id
        """

    def get_flight(
        self, flight_id: int
    ) -> tuple[Optional[Dict], str, float, str, str]:
        """Get flight data using the cache-aside pattern."""
        cache_key = self._generate_cache_key("flight", flight_id)
        start_time = time.perf_counter()
        cached_data = self.cache.get(cache_key)

        if cached_data:
            latency_ms = (time.perf_counter() - start_time) * 1000
            return json.loads(cached_data), "CACHE_HIT", latency_ms, cache_key, ""

        query_str = self._flight_query()
        with self.db_engine.connect() as conn:
            row = conn.execute(text(query_str), {"flight_id": flight_id}).fetchone()

        if not row:
            latency_ms = (time.perf_counter() - start_time) * 1000
            return None, "CACHE_MISS", latency_ms, cache_key, query_str.strip()

        flight_data = dict(row._mapping)
        for key, value in flight_data.items():
            if isinstance(value, datetime):
                flight_data[key] = value.isoformat()

        self.cache.set(cache_key, json.dumps(flight_data), self.default_ttl)
        latency_ms = (time.perf_counter() - start_time) * 1000
        return flight_data, "CACHE_MISS", latency_ms, cache_key, query_str.strip()

    def update_flight_departure(
        self,
        flight_id: int,
        new_departure: datetime,
        new_arrival: datetime,
        user: str = "system",
        comment: Optional[str] = None,
    ) -> tuple[bool, str]:
        """Atomically update cached data and publish its database update task."""
        cache_key = self._generate_cache_key("flight", flight_id)
        flight_data, _, _, _, _ = self.get_flight(flight_id)
        if not flight_data:
            return False, cache_key

        flight_data["departure"] = new_departure.isoformat()
        flight_data["arrival"] = new_arrival.isoformat()
        update_task = {
            "id": str(uuid4()),
            "flight_id": flight_id,
            "new_departure": new_departure.isoformat(),
            "new_arrival": new_arrival.isoformat(),
            "user": user,
            "comment": comment or "Flight time updated",
            "queued_at": datetime.now(timezone.utc).isoformat(),
            "attempts": 0,
        }

        pipeline = self.cache.client.pipeline(transaction=True)
        pipeline.setex(cache_key, self.default_ttl, json.dumps(flight_data))
        pipeline.rpush(self.QUEUE_KEY, json.dumps(update_task))
        pipeline.execute()
        return True, cache_key

    def get_queue_length(self) -> int:
        """Return all pending tasks, including tasks awaiting acknowledgement."""
        return self.cache.client.llen(self.QUEUE_KEY) + self.cache.client.llen(
            self.PROCESSING_KEY
        )

    def get_dead_letter_length(self) -> int:
        """Return the number of tasks that exhausted their retry budget."""
        return self.cache.client.llen(self.DEAD_LETTER_KEY)

    def recover_processing_tasks(self) -> int:
        """Move tasks abandoned by a previous single worker back to the queue."""
        recovered = 0
        while self.cache.client.lmove(
            self.PROCESSING_KEY, self.QUEUE_KEY, "RIGHT", "LEFT"
        ):
            recovered += 1
        return recovered

    def _acknowledge(self, task_json: str) -> None:
        """Remove a committed task from the processing list."""
        self.cache.client.lrem(self.PROCESSING_KEY, 1, task_json)

    def _retry_or_dead_letter(self, task_json: str, error: Exception) -> None:
        """Atomically move a failed task out of processing for retry or review."""
        try:
            task = json.loads(task_json)
            if not isinstance(task, dict):
                raise ValueError("Task payload must be a JSON object")
        except (json.JSONDecodeError, TypeError, ValueError):
            task = {"raw_task": task_json, "attempts": self.max_retries - 1}

        attempts = int(task.get("attempts", 0)) + 1
        task["attempts"] = attempts
        task["last_error"] = str(error)[:1000]
        task["last_attempt_at"] = datetime.now(timezone.utc).isoformat()
        destination = (
            self.DEAD_LETTER_KEY if attempts >= self.max_retries else self.QUEUE_KEY
        )

        pipeline = self.cache.client.pipeline(transaction=True)
        pipeline.lrem(self.PROCESSING_KEY, 1, task_json)
        if destination == self.DEAD_LETTER_KEY:
            flight_id = task.get("flight_id")
            if flight_id is not None:
                try:
                    cache_key = self._generate_cache_key("flight", int(flight_id))
                except (TypeError, ValueError):
                    cache_key = None
                if cache_key:
                    pipeline.delete(cache_key)
            pipeline.rpush(destination, json.dumps(task))
        else:
            # Retry before newer tasks so updates for one flight cannot reorder.
            pipeline.lpush(destination, json.dumps(task))
        pipeline.execute()

    def _apply_task(self, task: Dict, queries_executed: List[str]) -> None:
        """Apply one queue task in a database transaction."""
        flight_id = int(task["flight_id"])
        new_departure = datetime.fromisoformat(task["new_departure"])
        new_arrival = datetime.fromisoformat(task["new_arrival"])
        user = task["user"]
        comment = task["comment"]

        from_column = self._quote_identifier("from")
        to_column = self._quote_identifier("to")
        user_column = self._quote_identifier("user")
        select_query_str = f"""
            SELECT flight_id, flightno,
                   {from_column} AS from_id, {to_column} AS to_id,
                   departure, arrival, airline_id, airplane_id
            FROM flight
            WHERE flight_id = :flight_id
        """
        update_query_str = """
            UPDATE flight
            SET departure = :new_departure,
                arrival = :new_arrival
            WHERE flight_id = :flight_id
        """
        log_query_str = f"""
            INSERT INTO flight_log (
                log_date, {user_column}, flight_id,
                flightno_old, flightno_new,
                from_old, from_new,
                to_old, to_new,
                departure_old, departure_new,
                arrival_old, arrival_new,
                airplane_id_old, airplane_id_new,
                airline_id_old, airline_id_new,
                comment
            ) VALUES (
                :log_date, :user, :flight_id,
                :flightno, :flightno,
                :from_id, :from_id,
                :to_id, :to_id,
                :departure_old, :departure_new,
                :arrival_old, :arrival_new,
                :airplane_id, :airplane_id,
                :airline_id, :airline_id,
                :comment
            )
        """

        with self.db_engine.begin() as conn:
            queries_executed.append(select_query_str.strip())
            old_data = conn.execute(
                text(select_query_str), {"flight_id": flight_id}
            ).fetchone()
            if not old_data:
                raise LookupError(f"Flight {flight_id} no longer exists")

            old_dict = dict(old_data._mapping)
            if (
                old_dict["departure"] == new_departure
                and old_dict["arrival"] == new_arrival
            ):
                return

            queries_executed.append(update_query_str.strip())
            conn.execute(
                text(update_query_str),
                {
                    "flight_id": flight_id,
                    "new_departure": new_departure,
                    "new_arrival": new_arrival,
                },
            )

            queries_executed.append(log_query_str.strip())
            conn.execute(
                text(log_query_str),
                {
                    "log_date": datetime.now(timezone.utc),
                    "user": user,
                    "flight_id": flight_id,
                    "flightno": old_dict["flightno"],
                    "from_id": old_dict["from_id"],
                    "to_id": old_dict["to_id"],
                    "departure_old": old_dict["departure"],
                    "departure_new": new_departure,
                    "arrival_old": old_dict["arrival"],
                    "arrival_new": new_arrival,
                    "airplane_id": old_dict["airplane_id"],
                    "airline_id": old_dict["airline_id"],
                    "comment": comment,
                },
            )

    def process_queue(self, batch_size: int = 10) -> tuple[int, int, List[str]]:
        """Process a batch with at-least-once delivery and bounded retries."""
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")

        self.recover_processing_tasks()
        processed = 0
        failed = 0
        queries_executed: List[str] = []

        for _ in range(batch_size):
            task_json = self.cache.client.lmove(
                self.QUEUE_KEY, self.PROCESSING_KEY, "LEFT", "RIGHT"
            )
            if not task_json:
                break

            try:
                task = json.loads(task_json)
                if not isinstance(task, dict):
                    raise ValueError("Task payload must be a JSON object")
                self._apply_task(task, queries_executed)
                self._acknowledge(task_json)
                processed += 1
            except Exception as error:
                failed += 1
                self._retry_or_dead_letter(task_json, error)

        return processed, failed, queries_executed

    def flush_queue(self) -> int:
        """Process all pending updates, including bounded retry attempts."""
        total_processed = 0
        while self.get_queue_length() > 0:
            processed, _, _ = self.process_queue(batch_size=100)
            total_processed += processed
            if processed == 0 and self.get_queue_length() == 0:
                break
        return total_processed

    def verify_consistency(self, flight_id: int) -> Dict:
        """Compare the cached flight times with the database values."""
        cache_key = self._generate_cache_key("flight", flight_id)
        cached_data = self.cache.get(cache_key)
        cache_flight = json.loads(cached_data) if cached_data else None
        query_str = self._flight_query()

        with self.db_engine.connect() as conn:
            row = conn.execute(text(query_str), {"flight_id": flight_id}).fetchone()

        if not row:
            return {
                "consistent": False,
                "error": "Flight not found in database",
                "query": query_str.strip(),
                "cache_key": cache_key,
            }

        db_flight = dict(row._mapping)
        for key, value in db_flight.items():
            if isinstance(value, datetime):
                db_flight[key] = value.isoformat()

        if not cache_flight:
            return {
                "consistent": False,
                "reason": "Data exists in database but not in cache",
                "db_data": db_flight,
                "cache_data": None,
                "query": query_str.strip(),
                "cache_key": cache_key,
            }

        consistent = (
            cache_flight.get("departure") == db_flight.get("departure")
            and cache_flight.get("arrival") == db_flight.get("arrival")
        )
        return {
            "consistent": consistent,
            "db_data": db_flight,
            "cache_data": cache_flight,
            "query": query_str.strip(),
            "cache_key": cache_key,
            "queue_length": self.get_queue_length(),
            "dead_letter_length": self.get_dead_letter_length(),
        }

    def close(self) -> None:
        """Close database and cache connections."""
        self.db_engine.dispose()
        self.cache.close()


if __name__ == "__main__":
    from datetime import timedelta

    cache = WriteBehindCache()
    flight_id = 115
    print("=" * 60)
    print("Write-Behind Cache Pattern Demo")
    print("=" * 60)

    flight, source, latency, cache_key, _ = cache.get_flight(flight_id)
    print(f"Source: {source}; latency: {latency:.3f} ms; key: {cache_key}")
    if flight:
        current_departure = datetime.fromisoformat(flight["departure"])
        current_arrival = datetime.fromisoformat(flight["arrival"])
        success, _ = cache.update_flight_departure(
            flight_id,
            current_departure + timedelta(hours=2),
            current_arrival + timedelta(hours=2),
            user="demo_user",
            comment="Flight delayed by 2 hours",
        )
        print(f"Update queued: {success}; pending tasks: {cache.get_queue_length()}")
        processed, failed, _ = cache.process_queue()
        print(f"Processed: {processed}; failed attempts: {failed}")
    cache.close()
