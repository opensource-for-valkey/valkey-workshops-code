# Stampede Prevention Demo Implementation

## Overview

The stampede prevention demo (`samples/demo_stampede_prevention.py`) demonstrates how distributed locking prevents cache stampede when multiple concurrent requests try to fetch the same data simultaneously.

## Architecture

### Components

1. **WeatherAPICache** (`daos/weather_api_cache.py`)
   - Distributed locking with `acquire_lock()` and `release_lock()`
   - Cache operations with TTL support
   - Lock timeout management

2. **RequestMetrics** (dataclass)
   - Tracks individual request performance
   - Status tracking (cache_hit, cache_miss_api, lock_wait, timeout, error)
   - Duration and wait time measurement

3. **StampedeMetrics** (dataclass)
   - Aggregate metrics across all requests
   - Cache hit/miss rates
   - API call reduction calculation
   - Stampede prevention success tracking

4. **Demo Runner**
   - Simulates concurrent requests using threading
   - Configurable thread count and cities
   - Rich terminal output with tables and progress bars

## Key Features

### 1. Distributed Locking

```python
def acquire_lock(self, key: str, timeout: int = 10) -> str | None:
    """Acquire distributed lock and return its owner token."""
    lock_key = f"lock:{key}"
    token = secrets.token_urlsafe(24)
    return token if self.client.set(
        lock_key, token, nx=True, ex=timeout
    ) else None
```

**Benefits:**
- Only one thread makes the API call
- Others wait for cache to be populated
- Automatic lock expiration prevents deadlocks

### 2. Exponential Backoff

```python
for retry in range(max_retries):
    delay = base_delay * (2 ** retry) + random.uniform(0, 0.1)
    time.sleep(delay)
    cached_data = cache.get(cache_key)
    if cached_data:
        return cached_data
```

**Retry delays:**
- Retry 0: ~100ms
- Retry 1: ~200ms
- Retry 2: ~400ms
- Retry 3: ~800ms
- Retry 4: ~1600ms

**Total max wait:** ~3 seconds

### 3. Fail-Fast Behavior

- Maximum 5 retries by default
- Timeout after ~3 seconds
- Prevents indefinite waiting
- Returns None or fetches anyway

### 4. Double-Check Pattern

```python
if lock_acquired:
    # Double-check cache after acquiring lock
    cached_data = cache.get(cache_key)
    if cached_data:
        return cached_data  # Another thread populated it
    
    # Fetch from API
    weather_data = WeatherService.get_weather(...)
    cache.set(cache_key, weather_data)
```

## Usage

### Basic Usage

```bash
# Default: 1000 requests, 3 cities
uv run samples/demo_stampede_prevention.py
```

### Advanced Options

```bash
# High concurrency test
uv run samples/demo_stampede_prevention.py --requests 5000 --cities 5

# Verbose mode (shows thread-level details)
uv run samples/demo_stampede_prevention.py --verbose

# Interactive mode (step-by-step)
uv run samples/demo_stampede_prevention.py --interactive

# Flush cache before running
uv run samples/demo_stampede_prevention.py --flush

# Combine flags
uv run samples/demo_stampede_prevention.py -v -r 2000 -c 4 -f
```

## Output

### Metrics Table

```
┌─────────────────────────────────────────────────────────┐
│ 📊 Stampede Prevention Metrics - New York               │
├──────────────────────┬──────────────┬───────────────────┤
│ Metric               │ Value        │ Details           │
├──────────────────────┼──────────────┼───────────────────┤
│ Total Requests       │ 10           │ Concurrent threads│
│ Cache Hits           │ 9            │ 90.0% hit rate    │
│ Cache Misses         │ 1            │ Required API call │
│ API Calls            │ 1            │ 🎯 Should be 1    │
│ Lock Acquisitions    │ 1            │ Threads got lock  │
│ Lock Waits           │ 9            │ Avg wait: 245ms   │
│ Stampede Prevention  │ ✓ SUCCESS    │ Only 1 API call   │
└──────────────────────┴──────────────┴───────────────────┘
```

### Request Timeline (Verbose Mode)

```
┌────────────────────────────────────────────────────────┐
│ ⏱️ Request Timeline                                     │
├────────┬─────────────────┬──────────┬──────┬─────────┤
│ Thread │ Status          │ Duration │ Lock │ Retries │
├────────┼─────────────────┼──────────┼──────┼─────────┤
│ 1      │ ⚡ API Call     │ 1.234s   │ 🔒   │ —       │
│ 2      │ ✓ Cache Hit    │ 0.245s   │ ⏳   │ 2       │
│ 3      │ ✓ Cache Hit    │ 0.189s   │ ⏳   │ 1       │
│ 4      │ ✓ Cache Hit    │ 0.312s   │ ⏳   │ 2       │
│ ...    │ ...            │ ...      │ ...  │ ...     │
└────────┴─────────────────┴──────────┴──────┴─────────┘
```

### Overall Summary

```
┌─────────────────────────────────────────────────────────┐
│ 📈 Aggregate Results                                    │
├──────────────────────┬──────────────┬───────────────────┤
│ Metric               │ Value        │ Analysis          │
├──────────────────────┼──────────────┼───────────────────┤
│ Total Tests          │ 3            │ 3 cities tested   │
│ Total Requests       │ 30           │ 10 per city       │
│ Total API Calls      │ 3            │ 🎯 Ideal: 3       │
│ API Call Reduction   │ 90.0%        │ Prevented 27 calls│
│ Cache Hits           │ 27           │ 90.0% hit rate    │
│ Lock Waits           │ 27           │ Threads waited    │
│ Stampede Prevention  │ 3/3          │ Tests succeeded   │
└──────────────────────┴──────────────┴───────────────────┘
```

## Performance Benefits

### Without Stampede Prevention
- 10 concurrent requests → 10 API calls
- High API costs
- Risk of rate limiting
- All threads experience high latency

### With Stampede Prevention
- 10 concurrent requests → 1 API call
- 90% reduction in API calls
- Significant cost savings
- Only first thread has high latency
- Other threads get cached data quickly (~200-300ms)

## Test Scenarios

### Scenario 1: Major City (High Traffic)
```bash
uv run samples/demo_stampede_prevention.py --threads 20 --cities 1
```

**Expected:**
- 20 concurrent requests
- 1 API call
- 19 cache hits after waiting
- 95% API call reduction

### Scenario 2: Multiple Cities
```bash
uv run samples/demo_stampede_prevention.py --threads 10 --cities 5
```

**Expected:**
- 50 total requests (10 per city)
- 5 API calls (1 per city)
- 45 cache hits
- 90% API call reduction

### Scenario 3: Extreme Concurrency
```bash
uv run samples/demo_stampede_prevention.py --threads 50 --cities 1
```

**Expected:**
- 50 concurrent requests
- 1 API call
- 49 cache hits
- 98% API call reduction
- Some threads may timeout (increase max_retries if needed)

## Integration with Run All Demos

The demo is integrated into the automated test suite:

```bash
# Python version
python scripts/run_all_demos.py

# Bash version
./scripts/run_all_demos.sh
```

**Position:** Demo #6 (after Semantic Cache, before Multi-threaded Performance)

**Default args:** `--threads 10 --cities 3`

## Monitoring and Metrics

### Key Metrics to Track

1. **API Call Reduction**
   ```python
   reduction = ((total_requests - api_calls) / total_requests) * 100
   ```
   **Target:** > 90% for high concurrency

2. **Cache Hit Rate**
   ```python
   hit_rate = (cache_hits / total_requests) * 100
   ```
   **Target:** > 85% after first request

3. **Average Wait Time**
   ```python
   avg_wait = total_wait_time / lock_waits
   ```
   **Target:** < 500ms

4. **Timeout Rate**
   ```python
   timeout_rate = (timeouts / total_requests) * 100
   ```
   **Target:** < 5%

5. **Stampede Prevention Success**
   ```python
   success = (api_calls == 1) and (total_requests > 1)
   ```
   **Target:** 100% success rate

## Troubleshooting

### Issue: High Timeout Rate

**Symptoms:**
- Many threads timing out
- Timeout rate > 10%

**Solutions:**
1. Increase max_retries: `max_retries = 10`
2. Increase lock timeout: `timeout = 15`
3. Reduce thread count
4. Check API response time

### Issue: Multiple API Calls

**Symptoms:**
- API calls > 1 for same city
- Stampede prevention failed

**Solutions:**
1. Check lock acquisition logic
2. Verify Redis/Valkey connection
3. Ensure lock timeout > API call time
4. Check for race conditions

### Issue: Long Wait Times

**Symptoms:**
- Average wait time > 1 second
- Threads waiting too long

**Solutions:**
1. Reduce base_delay: `base_delay = 0.05`
2. Optimize API call performance
3. Increase cache TTL
4. Consider pre-warming cache

## Related Documentation

- [Stampede Prevention Concept](../concepts/stampede_prevention.md)
- [Weather API Cache DAO](../../daos/weather_api_cache.py)
- [Cache-Aside Pattern](../concepts/cache_aside.md)
- [Distributed Locking with Redis](https://redis.io/docs/manual/patterns/distributed-locks/)

## Future Enhancements

1. **Redlock Algorithm**
   - Multi-node lock acquisition
   - Higher reliability for distributed systems

2. **Lock Metrics Dashboard**
   - Real-time lock contention visualization
   - Historical performance tracking

3. **Adaptive Backoff**
   - Dynamic retry delays based on system load
   - Machine learning-based optimization

4. **Circuit Breaker Integration**
   - Prevent cascading failures
   - Automatic fallback mechanisms

5. **Prometheus Metrics Export**
   - Integration with monitoring systems
   - Alerting on high timeout rates
