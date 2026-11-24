"""
Cache-Aside / Lazy Loading Pattern Implementation

Supports multiple database engines (MySQL, MariaDB, PostgreSQL) and
cache engines (Redis, Valkey, Memcached) via environment variables.
"""

import os
from rich.console import Console
print = Console(soft_wrap=True).print
import sys
from pathlib import Path

# Add parent directory to path when running as script
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent))

import hashlib
import json
from typing import Optional, Tuple
from dotenv import load_dotenv
from sqlalchemy import text
from core import get_db_engine, get_cache_client

# Load environment variables
load_dotenv(os.environ.get("WORKSHOP_ENV_FILE", ".env"))


class CacheAside:
    """Cache-aside pattern implementation with pluggable backends."""
    
    def __init__(self, db_engine=None, cache=None):
        """Initialize database and cache connections from environment variables."""
        self.db_engine = db_engine or get_db_engine()
        self.cache = cache or get_cache_client()
        self.default_ttl = int(os.getenv("CACHE_TTL", "3600"))  # 1 hour default
    
    def _generate_cache_key(self, query: str) -> str:
        """Generate cache key from SQL query using SHA256 hash."""
        query_hash = hashlib.sha256(query.encode()).hexdigest()
        return f"query:{query_hash}"
    
    def execute_query(
        self, 
        query: str, 
        ttl: Optional[int] = None,
        force_refresh: bool = False
    ) -> Tuple[list, str, float]:
        """
        Execute SQL query with cache-aside pattern.
        
        Args:
            query: SQL query string
            ttl: Cache TTL in seconds (uses default if None)
            force_refresh: If True, bypass cache and refresh from DB
        
        Returns:
            Tuple of (results, source, latency_ms)
            - results: List of dictionaries with query results
            - source: "CACHE_HIT" or "CACHE_MISS"
            - latency_ms: Query execution time in milliseconds
        """
        import time
        
        if ttl is None:
            ttl = self.default_ttl
        
        cache_key = self._generate_cache_key(query)
        
        # 1. Try cache first (unless force refresh)
        if not force_refresh:
            start = time.time()
            cached_data = self.cache.get(cache_key)
            latency = (time.time() - start) * 1000
            
            if cached_data:
                results = json.loads(cached_data)
                return results, "CACHE_HIT", latency
        
        # 2. Cache miss - query database
        start = time.time()
        with self.db_engine.connect() as conn:
            result = conn.execute(text(query))
            # Convert rows to list of dicts
            results = [dict(row._mapping) for row in result]
        latency = (time.time() - start) * 1000
        
        # 3. Store in cache
        if results:
            self.cache.set(cache_key, json.dumps(results, default=str), ttl)
        
        return results, "CACHE_MISS", latency
    
    def invalidate_query(self, query: str) -> bool:
        """
        Invalidate cached query result.
        
        Args:
            query: SQL query string to invalidate
        
        Returns:
            True if cache entry was deleted, False otherwise
        """
        cache_key = self._generate_cache_key(query)
        return self.cache.delete(cache_key)
    
    def close(self):
        """Close database and cache connections."""
        self.db_engine.dispose()
        self.cache.close()


# Example usage
if __name__ == "__main__":
    # Initialize cache-aside handler
    cache = CacheAside()
    
    # Example query
    query = """
        SELECT 
            airline_id,
            iata,
            airlinename,
            base_airport
        FROM airline
        WHERE airline_id = 1
    """
    
    print("=" * 60)
    print("Cache-Aside Pattern Demo")
    print("=" * 60)
    
    # First execution (cache miss)
    print("\n1. First execution (should be CACHE_MISS ❌):")
    results, source, latency = cache.execute_query(query)
    print(f"   Source: {source}")
    print(f"   Latency: {latency:.3f} ms")
    print(f"   Results: {results}")
    
    # Second execution (cache hit)
    print("\n2. Second execution (should be CACHE_HIT ✅):")
    results, source, latency = cache.execute_query(query)
    print(f"   Source: {source}")
    print(f"   Latency: {latency:.3f} ms")
    print(f"   Results: {results}")
    
    # Force refresh
    print("\n3. Force refresh (bypasses cache ⏭️):")
    results, source, latency = cache.execute_query(query, force_refresh=True)
    print(f"   Source: {source}")
    print(f"   Latency: {latency:.3f} ms")
    
    # Invalidate cache
    print("\n4. Invalidating cache...")
    invalidated = cache.invalidate_query(query)
    print(f"   Cache invalidated: {invalidated}")
    
    # Query after invalidation
    print("\n5. Query after invalidation (should be CACHE_MISS ❌):")
    results, source, latency = cache.execute_query(query)
    print(f"   Source: {source}")
    print(f"   Latency: {latency:.3f} ms")
    
    # Cleanup
    cache.close()
    print("\n" + "=" * 60)
