"""Weather API cache with TTL support and distributed locking."""

import json
import secrets
import sys
from pathlib import Path
from typing import Any, Optional

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent))

from core import get_cache_client


_RELEASE_LOCK_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
end
return 0
"""


class WeatherAPICache:
    """Weather API cache with transport failures distinct from cache misses."""

    def __init__(
        self,
        default_ttl: int = 900,
        verbose: bool = False,
        cache: Optional[Any] = None,
        ping: bool = True,
    ):
        """Initialize an injectable Valkey/Redis cache connection."""
        self.default_ttl = default_ttl
        self.verbose = verbose
        self.cache = cache or get_cache_client()
        self.client = self.cache.client

        if ping:
            self.client.ping()
            if self.verbose:
                print(f"Connected to Valkey at {self.cache.host}:{self.cache.port}")

    def get(self, key: str) -> Optional[Any]:
        """Return deserialized data, or None only when the key is absent."""
        value = self.cache.get(key)
        return json.loads(value) if value is not None else None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Serialize and cache a value; backend failures propagate."""
        effective_ttl = self.default_ttl if ttl is None else ttl
        serialized_value = json.dumps(value, default=str)
        return self.cache.set(key, serialized_value, effective_ttl)

    def acquire_lock(self, key: str, timeout: int = 10) -> Optional[str]:
        """Acquire a distributed lock and return its unique owner token."""
        lock_key = f"lock:{key}"
        token = secrets.token_urlsafe(24)
        return token if self.client.set(lock_key, token, nx=True, ex=timeout) else None

    def release_lock(self, key: str, token: str) -> bool:
        """Release the lock only when token still owns it."""
        return bool(
            self.client.eval(_RELEASE_LOCK_SCRIPT, 1, f"lock:{key}", token)
        )

    def delete(self, key: str) -> bool:
        """Delete a cache entry."""
        return self.cache.delete(key)

    def clear(self) -> None:
        """Clear the selected cache when explicitly enabled by configuration."""
        self.cache.flush_all()
        if self.verbose:
            print("Cache cleared successfully")

    def keys(self, pattern: str = "*") -> list:
        """Return keys matching a pattern."""
        return self.client.keys(pattern)

    def close(self) -> None:
        """Close the cache connection."""
        self.cache.close()


if __name__ == "__main__":
    import time

    print("=" * 60)
    print("Weather API Cache Demo")
    print("=" * 60)
    cache = WeatherAPICache(default_ttl=900, verbose=True)
    weather_data = {
        "coord": {"lon": -122.08, "lat": 37.39},
        "weather": [{"id": 800, "main": "Clear", "description": "clear sky"}],
        "main": {"temp": 72.5, "feels_like": 70.2, "humidity": 45},
        "name": "Mountain View",
    }
    cache_key = "weather:us:94043"
    cache.set(cache_key, weather_data)
    print(f"Retrieved: {cache.get(cache_key)}")
    lock_token = cache.acquire_lock(cache_key, timeout=5)
    print(f"Lock acquired: {bool(lock_token)}")
    if lock_token:
        time.sleep(1)
        cache.release_lock(cache_key, lock_token)
    print(f"Weather keys: {cache.keys('weather:*')}")
    print(f"Deleted: {cache.delete(cache_key)}")
    cache.close()
