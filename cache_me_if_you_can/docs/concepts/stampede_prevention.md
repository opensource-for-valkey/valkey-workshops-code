# Stampede Prevention with Distributed Locking

## Overview

Cache stampede (also known as "thundering herd") occurs when multiple concurrent requests try to fetch the same missing cache entry simultaneously, resulting in multiple expensive operations (e.g., API calls, database queries) for the same data.

## The Problem

Without stampede prevention:
```
Time: T0
┌─────────┐  ┌─────────┐  ┌─────────┐
│Thread 1 │  │Thread 2 │  │Thread 3 │
└────┬────┘  └────┬────┘  └────┬────┘
     │            │            │
     ├─── Cache miss ──────────┤
     │            │            │
     ├─── API call ────────────┤  ← 3 API calls!
     │            │            │
     ├─── Cache set ───────────┤
     │            │            │
```

**Result**: 3 API calls for the same data = wasted resources, higher costs, potential rate limiting

## The Solution: Distributed Locking

With distributed locking:
```
Time: T0
┌─────────┐  ┌─────────┐  ┌─────────┐
│Thread 1 │  │Thread 2 │  │Thread 3 │
└────┬────┘  └────┬────┘  └────┬────┘
     │            │            │
     ├─── Cache miss ──────────┤
     │            │            │
     ├─ Acquire lock           │
     │    (SUCCESS)            │
     │            │            │
     │            ├─ Try lock  │
     │            │  (FAIL)    │
     │            │            ├─ Try lock
     │            │            │  (FAIL)
     │            │            │
     ├─── API call             │  ← Only 1 API call!
     │            │            │
     ├─── Cache set            │
     │            │            │
     ├─ Release lock           │
     │            │            │
     │            ├─ Cache hit │
     │            │            ├─ Cache hit
     │            │            │
```

**Result**: 1 API call, other threads wait and get cached data

## Implementation

### 1. Distributed Lock with Redis/Valkey

```python
def acquire_lock(self, key: str, timeout: int = 10) -> str | None:
    """
    Acquire a distributed lock using SET NX (set if not exists).
    
    Args:
        key: The cache key to lock
        timeout: Lock timeout in seconds
    
    Returns:
        Unique owner token if acquired, otherwise None
    """
    lock_key = f"lock:{key}"
    token = secrets.token_urlsafe(24)
    return token if self.client.set(
        lock_key, token, nx=True, ex=timeout
    ) else None

def release_lock(self, key: str, token: str) -> bool:
    """Release the distributed lock only if token still owns it."""
    lock_key = f"lock:{key}"
    return bool(self.client.eval(
        """
        if redis.call('GET', KEYS[1]) == ARGV[1] then
            return redis.call('DEL', KEYS[1])
        end
        return 0
        """,
        1,
        lock_key,
        token,
    ))
```

### 2. Fetch with Stampede Protection

```python
def fetch_with_protection(cache_key: str):
    # Try cache first
    cached_data = cache.get(cache_key)
    if cached_data:
        return cached_data  # Cache hit
    
    # Cache miss - try to acquire lock
    lock_token = cache.acquire_lock(cache_key, timeout=10)
    if lock_token:
        try:
            # Double-check cache after acquiring lock
            cached_data = cache.get(cache_key)
            if cached_data:
                return cached_data
            
            # Fetch from source (API, DB, etc.)
            data = fetch_from_source()
            cache.set(cache_key, data)
            return data
        finally:
            cache.release_lock(cache_key, lock_token)
    else:
        # Could not acquire lock - wait and retry
        return wait_for_cache_with_backoff(cache_key)
```

### 3. Exponential Backoff

When a thread fails to acquire the lock, it should retry with exponential backoff:

```python
def wait_for_cache_with_backoff(cache_key: str, max_retries: int = 5):
    base_delay = 0.1  # 100ms
    
    for retry in range(max_retries):
        # Exponential backoff: 100ms, 200ms, 400ms, 800ms, 1600ms
        delay = base_delay * (2 ** retry) + random.uniform(0, 0.1)
        time.sleep(delay)
        
        # Try to get from cache
        cached_data = cache.get(cache_key)
        if cached_data:
            return cached_data
    
    # Timeout - fail fast or fetch anyway
    return None  # or fetch_from_source()
```

## Key Features

### 1. Lock Timeout
- Prevents indefinite waiting if lock holder crashes
- Typical timeout: 10 seconds
- Lock automatically expires after timeout

### 2. Double-Check Pattern
- Check cache after acquiring lock
- Another thread might have populated it
- Avoids unnecessary work

### 3. Fail-Fast Behavior
- Maximum retry limit prevents infinite waiting
- Timeout returns None or fetches anyway
- Prevents system hangs

### 4. Exponential Backoff
- Reduces lock contention
- Spreads out retry attempts
- Adds random jitter to prevent synchronized retries

## Performance Benefits

### Without Stampede Prevention
- **10 concurrent requests** → **10 API calls**
- High API costs
- Risk of rate limiting
- Increased latency for all requests

### With Stampede Prevention
- **10 concurrent requests** → **1 API call**
- 90% reduction in API calls
- Significant cost savings
- Only first thread has high latency, others get cached data quickly

## Use Cases

### 1. High-Traffic Scenarios
- Major cities weather data
- Popular products in e-commerce
- Trending content
- Real-time sports scores

### 2. Expensive Operations
- External API calls with rate limits
- Complex database queries
- Machine learning model inference
- Large file processing

### 3. Cost Optimization
- Reducing API call costs
- Minimizing database load
- Preventing rate limit exhaustion
- Optimizing resource usage

## Best Practices

### 1. Lock Timeout
```python
# Too short: Risk of multiple API calls
acquire_lock(key, timeout=1)  # ❌

# Too long: Threads wait unnecessarily if holder crashes
acquire_lock(key, timeout=60)  # ❌

# Just right: Enough time for API call, not too long
acquire_lock(key, timeout=10)  # ✅
```

### 2. Retry Strategy
```python
# No retries: Threads give up too easily
max_retries = 0  # ❌

# Too many retries: Threads wait too long
max_retries = 20  # ❌

# Balanced: Enough retries, reasonable wait time
max_retries = 5  # ✅ (total wait: ~3 seconds)
```

### 3. Cache TTL
```python
# TTL should be longer than lock timeout
lock_timeout = 10  # seconds
cache_ttl = 900    # 15 minutes ✅

# Avoid: TTL shorter than lock timeout
lock_timeout = 10  # seconds
cache_ttl = 5      # 5 seconds ❌
```

## Monitoring Metrics

Track these metrics to measure effectiveness:

1. **API Call Reduction**: `(requests - api_calls) / requests * 100%`
2. **Lock Wait Rate**: `lock_waits / total_requests * 100%`
3. **Average Wait Time**: Total wait time / lock waits
4. **Timeout Rate**: `timeouts / total_requests * 100%`
5. **Stampede Prevention Success**: API calls = 1 for N concurrent requests

## Demo

Run the stampede prevention demo:

```bash
# Basic demo: 10 threads, 3 cities
uv run samples/demo_stampede_prevention.py

# High concurrency
uv run samples/demo_stampede_prevention.py --threads 20 --cities 5

# Verbose mode with thread details
uv run samples/demo_stampede_prevention.py --verbose

# Interactive step-by-step
uv run samples/demo_stampede_prevention.py --interactive
```

## Related Patterns

- **Cache-Aside**: Base pattern for lazy loading
- **Write-Through**: Ensures cache consistency on writes
- **Circuit Breaker**: Prevents cascading failures
- **Rate Limiting**: Controls request rate to external services

## References

- [Cache Stampede Problem](https://en.wikipedia.org/wiki/Cache_stampede)
- [Redis SET NX](https://redis.io/commands/set/)
- [Distributed Locking with Redis](https://redis.io/docs/manual/patterns/distributed-locks/)
- [Exponential Backoff](https://en.wikipedia.org/wiki/Exponential_backoff)
