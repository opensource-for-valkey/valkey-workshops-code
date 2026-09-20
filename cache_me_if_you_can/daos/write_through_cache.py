"""
Write-Through Cache Pattern Implementation

In write-through caching, updates are written to both the database
and cache simultaneously, ensuring consistency.

This module provides:
- WriteThroughCache: Main class for write-through cache operations
- Cache-aside reads with automatic cache population
- Write-through updates with database and cache synchronization
- Data consistency verification between database and cache
"""

import os
import sys
from pathlib import Path

# Add parent directory to path when running as script
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent))

import json
from datetime import datetime, timezone
from typing import Optional, Dict
from sqlalchemy import text

from core import get_db_engine, get_cache_client, quote_identifier


class WriteThroughCache:
    """Write-through cache implementation for flight data."""
    
    def __init__(self):
        """Initialize database and cache connections."""
        self.db_engine = get_db_engine()
        self.cache = get_cache_client()
        self.default_ttl = int(os.getenv("CACHE_TTL", "3600"))
        self._cache_sync_required: set[str] = set()
    
    def _generate_cache_key(self, entity_type: str, entity_id: int) -> str:
        """Generate cache key for entity."""
        return f"{entity_type}:{entity_id}"

    def _flight_query(self) -> str:
        """Build the shared flight query with portable reserved identifiers."""
        from_column = quote_identifier(self.db_engine, "from")
        to_column = quote_identifier(self.db_engine, "to")
        return f"""
            SELECT
                f.flight_id,
                f.flightno,
                f.departure,
                f.arrival,
                f.airline_id,
                f.airplane_id,
                dep.iata as from_airport,
                arr.iata as to_airport,
                al.airlinename
            FROM flight f
            JOIN airport dep ON f.{from_column} = dep.airport_id
            JOIN airport arr ON f.{to_column} = arr.airport_id
            JOIN airline al ON f.airline_id = al.airline_id
            WHERE f.flight_id = :flight_id
        """
    
    def get_flight(self, flight_id: int) -> tuple[Optional[Dict], str, float, str, str]:
        """
        Get flight data using cache-aside pattern.
        
        Args:
            flight_id: Flight ID to retrieve
        
        Returns:
            Tuple of (flight_data, source, latency_ms, cache_key, query_str)
            - flight_data: Flight data dictionary or None if not found
            - source: "CACHE_HIT" or "CACHE_MISS"
            - latency_ms: Query latency in milliseconds
            - cache_key: Cache key used
            - query_str: SQL query executed (empty string if cache hit)
        """
        import time
        
        cache_key = self._generate_cache_key("flight", flight_id)
        
        # Bypass a potentially stale value while a prior write is reconciling.
        start_time = time.perf_counter()
        cached_data = (
            None
            if cache_key in self._cache_sync_required
            else self.cache.get(cache_key)
        )
        
        if cached_data:
            latency_ms = (time.perf_counter() - start_time) * 1000
            return json.loads(cached_data), "CACHE_HIT", latency_ms, cache_key, ""
        
        # Cache miss - query database
        query_str = self._flight_query()
        
        query = text(query_str)
        
        with self.db_engine.connect() as conn:
            result = conn.execute(query, {"flight_id": flight_id})
            row = result.fetchone()

            if not row:
                latency_ms = (time.perf_counter() - start_time) * 1000
                return None, "CACHE_MISS", latency_ms, cache_key, query_str.strip()
            
            flight_data = dict(row._mapping)
            
            # Convert datetime objects to strings for JSON serialization
            for key, value in flight_data.items():
                if isinstance(value, datetime):
                    flight_data[key] = value.isoformat()
            
            # Store in cache
            self.cache.set(cache_key, json.dumps(flight_data), self.default_ttl)
            self._cache_sync_required.discard(cache_key)
            
            latency_ms = (time.perf_counter() - start_time) * 1000
            return flight_data, "CACHE_MISS", latency_ms, cache_key, query_str.strip()
    
    def update_flight_departure(
        self, 
        flight_id: int, 
        new_departure: datetime,
        new_arrival: datetime,
        user: str = "system",
        comment: Optional[str] = None
    ) -> tuple[bool, list[str]]:
        """
        Update flight departure/arrival times using write-through pattern.
        
        This ensures data consistency by:
        1. Writing to the database first (source of truth)
        2. Updating the cache immediately
        3. Logging the change in flight_log
        
        Args:
            flight_id: Flight ID to update
            new_departure: New departure datetime
            new_arrival: New arrival datetime
            user: Username making the change
            comment: Optional comment explaining the change
        
        Returns:
            Tuple of (success, queries_executed)
            - success: True if update successful, False otherwise
            - queries_executed: List of SQL queries executed
        """
        queries_executed = []
        cache_key = self._generate_cache_key("flight", flight_id)
        if not hasattr(self, "_cache_sync_required"):
            self._cache_sync_required = set()
        self._cache_sync_required.add(cache_key)
        
        try:
            with self.db_engine.begin() as conn:
                # Get current flight data for logging
                from_column = quote_identifier(self.db_engine, "from")
                to_column = quote_identifier(self.db_engine, "to")
                user_column = quote_identifier(self.db_engine, "user")
                select_query_str = f"""
                    SELECT flight_id, flightno,
                           {from_column} AS from_id, {to_column} AS to_id,
                           departure, arrival, airline_id, airplane_id
                    FROM flight
                    WHERE flight_id = :flight_id
                """
                queries_executed.append(select_query_str.strip())
                
                query = text(select_query_str)
                result = conn.execute(query, {"flight_id": flight_id})
                old_data = result.fetchone()
                
                if not old_data:
                    return False, queries_executed
                
                old_dict = dict(old_data._mapping)
                
                # Update flight in database
                update_query_str = """
                    UPDATE flight
                    SET departure = :new_departure,
                        arrival = :new_arrival
                    WHERE flight_id = :flight_id
                """
                queries_executed.append(update_query_str.strip())
                
                update_query = text(update_query_str)
                conn.execute(update_query, {
                    "flight_id": flight_id,
                    "new_departure": new_departure,
                    "new_arrival": new_arrival
                })
                
                # Log the change
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
                queries_executed.append(log_query_str.strip())
                
                log_query = text(log_query_str)
                conn.execute(log_query, {
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
                    "comment": comment or "Flight time updated"
                })

                # Invalidate stale data before commit. If invalidation fails,
                # the exception rolls the database transaction back.
                self.cache.delete(cache_key)

        except Exception as e:
            self._cache_sync_required.discard(cache_key)
            return False, queries_executed

        # Delete again after commit in case a concurrent reader repopulated the
        # old value between the first invalidation and the database commit.
        try:
            self.cache.delete(cache_key)
            self.get_flight(flight_id)
        except Exception:
            # Keep the bypass marker. A later read will ignore any stale value,
            # reload from the database, and clear the marker after cache set.
            return True, queries_executed

        return True, queries_executed
    
    def verify_consistency(self, flight_id: int) -> Dict:
        """
        Verify data consistency between database and cache.
        
        Args:
            flight_id: Flight ID to verify
        
        Returns:
            Dictionary with consistency check results
        """
        cache_key = self._generate_cache_key("flight", flight_id)
        
        # Get from cache
        cached_data = self.cache.get(cache_key)
        cache_flight = json.loads(cached_data) if cached_data else None
        
        # Get from database
        query_str = self._flight_query()
        
        query = text(query_str)
        
        with self.db_engine.connect() as conn:
            result = conn.execute(query, {"flight_id": flight_id})
            row = result.fetchone()
            
            if not row:
                return {"consistent": False, "error": "Flight not found in database", "query": query_str.strip(), "cache_key": cache_key}
            
            db_flight = dict(row._mapping)
            for key, value in db_flight.items():
                if isinstance(value, datetime):
                    db_flight[key] = value.isoformat()
        
        # Compare
        if not cache_flight:
            return {
                "consistent": False,
                "reason": "Data exists in database but not in cache",
                "db_data": db_flight,
                "cache_data": None,
                "query": query_str.strip(),
                "cache_key": cache_key
            }
        
        # Check key fields
        consistent = (
            cache_flight.get("departure") == db_flight.get("departure") and
            cache_flight.get("arrival") == db_flight.get("arrival")
        )
        
        return {
            "consistent": consistent,
            "db_data": db_flight,
            "cache_data": cache_flight,
            "query": query_str.strip(),
            "cache_key": cache_key
        }
    
    def close(self):
        """Close database and cache connections."""
        self.db_engine.dispose()
        self.cache.close()


# Example usage
if __name__ == "__main__":
    from datetime import timedelta
    
    # Initialize write-through cache handler
    cache = WriteThroughCache()
    
    # Use a specific flight ID
    flight_id = 115
    
    print("=" * 60)
    print("Write-Through Cache Pattern Demo")
    print("=" * 60)
    
    # Step 1: Initial read (cache miss)
    print("\n1. First read (should be CACHE_MISS ❌):")
    flight, source, latency, cache_key, query = cache.get_flight(flight_id)
    print(f"   Source: {source}")
    print(f"   Latency: {latency:.3f} ms")
    print(f"   Cache Key: {cache_key}")
    if flight:
        print(f"   Flight: {flight['flightno']} - {flight['from_airport']} → {flight['to_airport']}")
    
    # Step 2: Second read (cache hit)
    print("\n2. Second read (should be CACHE_HIT ✅):")
    flight, source, latency, cache_key, query = cache.get_flight(flight_id)
    print(f"   Source: {source}")
    print(f"   Latency: {latency:.3f} ms")
    
    if flight:
        # Step 3: Update flight times (write-through)
        print("\n3. Update flight times (write-through):")
        current_departure = datetime.fromisoformat(flight["departure"])
        current_arrival = datetime.fromisoformat(flight["arrival"])
        
        new_departure = current_departure + timedelta(hours=2)
        new_arrival = current_arrival + timedelta(hours=2)
        
        print(f"   Old departure: {current_departure}")
        print(f"   New departure: {new_departure}")
        
        success, queries = cache.update_flight_departure(
            flight_id=flight_id,
            new_departure=new_departure,
            new_arrival=new_arrival,
            user="demo_user",
            comment="Flight delayed by 2 hours"
        )
        
        if success:
            print(f"   ✓ Update successful ({len(queries)} queries executed)")
        else:
            print(f"   ✗ Update failed")
        
        # Step 4: Verify consistency
        print("\n4. Verify consistency:")
        consistency = cache.verify_consistency(flight_id)
        if consistency["consistent"]:
            print(f"   ✓ Data is CONSISTENT between database and cache")
        else:
            print(f"   ✗ Data INCONSISTENCY detected!")
            print(f"   Reason: {consistency.get('reason', 'Unknown')}")
        
        # Step 5: Restore original times
        print("\n5. Restore original times:")
        success, queries = cache.update_flight_departure(
            flight_id=flight_id,
            new_departure=current_departure,
            new_arrival=current_arrival,
            user="demo_user",
            comment="Restoring original times"
        )
        
        if success:
            print(f"   ✓ Original times restored")
        else:
            print(f"   ✗ Restore failed")
    
    # Cleanup
    cache.close()
    print("\n" + "=" * 60)
