# Stampede Prevention - Quick Reference Card

## The Problem

```
❌ WITHOUT STAMPEDE PREVENTION
┌─────────┐  ┌─────────┐  ┌─────────┐
│Thread 1 │  │Thread 2 │  │Thread 3 │
└────┬────┘  └────┬────┘  └────┬────┘
     │            │            │
     ├─── Cache miss ──────────┤
     ├─── API call ────────────┤  ← 3 API calls!
     ├─── Cache set ───────────┤
```

**Result:** N requests → N API calls 💸

## The Solution

```
✅ WITH STAMPEDE PREVENTION
┌─────────┐  ┌─────────┐  ┌─────────┐
│Thread 1 │  │Thread 2 │  │Thread 3 │
└────┬────┘  └────┬────┘  └────┬────┘
     │            │            │
     ├─── Cache miss ──────────┤
     ├─ Acquire lock           │
     │            ├─ Lock wait │
     │            │            ├─ Lock wait
     ├─── API call             │  ← 1 API call!
     ├─── Cache set            │
     ├─ Release lock           │
     │            ├─ Cache hit │
     │            │            ├─ Cache hit
```

**Result:** N requests → 1 API call 🎯

## Quick Start

```bash
# Basic demo
uv run samples/demo_stampede_prevention.py

# High concurrency
uv run samples/demo_stampede_prevention.py --threads 20 --cities 5

# Verbose mode
uv run samples/demo_stampede_prevention.py -v

# Interactive
uv run samples/demo_stampede_prevention.py -i -v
```

## Core Implementation

### 1. Acquire Lock
```python
lock_token = cache.acquire_lock(cache_key, timeout=10)
```

### 2. Double-Check Cache
```python
if lock_token:
    cached_data = cache.get(cache_key)
    if cached_data:
        return cached_data  # Another thread populated it
```

### 3. Fetch and Cache
```python
    data = fetch_from_api()
    cache.set(cache_key, data)
    return data
```

### 4. Release Lock
```python
finally:
    cache.release_lock(cache_key, lock_token)
```

### 5. Wait with Backoff
```python
else:  # Could not acquire lock
    for retry in range(max_retries):
        delay = base_delay * (2 ** retry)
        time.sleep(delay)
        cached_data = cache.get(cache_key)
        if cached_data:
            return cached_data
```

## Key Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `lock_timeout` | 10s | Lock expiration time |
| `max_retries` | 5 | Maximum retry attempts |
| `base_delay` | 0.1s | Initial backoff delay |
| `cache_ttl` | 900s | Cache entry lifetime |

## Backoff Schedule

| Retry | Delay | Cumulative |
|-------|-------|------------|
| 0 | ~100ms | 100ms |
| 1 | ~200ms | 300ms |
| 2 | ~400ms | 700ms |
| 3 | ~800ms | 1.5s |
| 4 | ~1600ms | 3.1s |

## Performance Metrics

### Target Metrics
- **API Call Reduction:** > 90%
- **Cache Hit Rate:** > 85%
- **Avg Wait Time:** < 500ms
- **Timeout Rate:** < 5%
- **Success Rate:** 100%

### Example Results
```
10 concurrent requests:
├─ API calls: 1 (90% reduction)
├─ Cache hits: 9
├─ Lock waits: 9
├─ Avg wait: 245ms
└─ Timeouts: 0
```

## Use Cases

### ✅ Good For
- High-traffic endpoints
- Expensive API calls
- Rate-limited services
- Complex database queries
- ML model inference

### ❌ Not Needed For
- Low-traffic endpoints
- Cheap operations
- Already cached data
- Single-threaded apps

## Common Patterns

### Pattern 1: API Call Protection
```python
def get_weather(city):
    cache_key = f"weather:{city}"
    
    # Try cache first
    data = cache.get(cache_key)
    if data:
        return data
    
    # Acquire lock
    lock_token = cache.acquire_lock(cache_key)
    if lock_token:
        try:
            # Double-check
            data = cache.get(cache_key)
            if data:
                return data
            
            # Fetch from API
            data = api.get_weather(city)
            cache.set(cache_key, data)
            return data
        finally:
            cache.release_lock(cache_key, lock_token)
    else:
        # Wait for cache
        return wait_for_cache(cache_key)
```

### Pattern 2: Database Query Protection
```python
def get_expensive_report(params):
    cache_key = f"report:{hash(params)}"
    
    data = cache.get(cache_key)
    if data:
        return data
    
    lock_token = cache.acquire_lock(cache_key)
    if lock_token:
        try:
            data = cache.get(cache_key)
            if data:
                return data
            
            data = db.execute_complex_query(params)
            cache.set(cache_key, data, ttl=3600)
            return data
        finally:
            cache.release_lock(cache_key, lock_token)
    else:
        return wait_for_cache(cache_key)
```

## Troubleshooting

### Problem: High Timeout Rate

**Symptoms:** > 10% timeouts

**Solutions:**
```python
# Increase retries
max_retries = 10

# Increase lock timeout
cache.acquire_lock(key, timeout=15)

# Reduce thread count
--threads 5
```

### Problem: Multiple API Calls

**Symptoms:** API calls > 1 for same key

**Solutions:**
- Check lock acquisition logic
- Verify Redis connection
- Ensure lock timeout > API call time
- Check for race conditions

### Problem: Long Wait Times

**Symptoms:** Avg wait > 1 second

**Solutions:**
```python
# Reduce base delay
base_delay = 0.05

# Optimize API performance
# Increase cache TTL
cache.set(key, data, ttl=1800)
```

## Best Practices

### ✅ Do
- Use lock timeout > API call time
- Implement exponential backoff
- Add random jitter to delays
- Double-check cache after lock
- Release lock in finally block
- Monitor timeout rates
- Set appropriate cache TTL

### ❌ Don't
- Use lock timeout < API call time
- Retry indefinitely
- Forget to release locks
- Skip double-check pattern
- Ignore timeout metrics
- Use same delay for all retries

## Monitoring

### Key Metrics to Track
```python
# API call reduction
reduction = (requests - api_calls) / requests * 100

# Cache hit rate
hit_rate = cache_hits / total_requests * 100

# Average wait time
avg_wait = total_wait_time / lock_waits

# Timeout rate
timeout_rate = timeouts / total_requests * 100

# Success rate
success = (api_calls == 1) and (requests > 1)
```

### Alert Thresholds
- API call reduction < 80% → Warning
- Timeout rate > 10% → Critical
- Avg wait time > 1s → Warning
- Success rate < 95% → Critical

## Command Reference

```bash
# Basic usage
uv run samples/demo_stampede_prevention.py

# Options
--requests, -r   # Concurrent requests (1-10000, default: 1000)
--cities, -c     # Cities to test (1-5)
--verbose, -v    # Show details
--interactive, -i # Step-by-step
--flush, -f      # Clear cache first

# Examples
uv run samples/demo_stampede_prevention.py -r 1000 -c 3
uv run samples/demo_stampede_prevention.py -v -i
uv run samples/demo_stampede_prevention.py -f -r 5000
```

## Related Patterns

- **Cache-Aside:** Base pattern for lazy loading
- **Write-Through:** Consistency on writes
- **Circuit Breaker:** Prevent cascading failures
- **Rate Limiting:** Control request rate

## Learn More

- [Full Concept Guide](stampede_prevention.md)
- [Implementation Details](../implementation/stampede_prevention_demo.md)
- [Demo Script](../../samples/demo_stampede_prevention.py)
- [Unit Tests](../../tests/test_stampede_prevention.py)

## Quick Decision Tree

```
Need to cache expensive operation?
├─ Yes → High traffic expected?
│        ├─ Yes → Use stampede prevention ✅
│        └─ No → Use simple cache-aside
└─ No → Don't cache
```

## Cost Savings Example

### Scenario: Weather API
- **Cost per call:** $0.001
- **Requests per day:** 100,000
- **Concurrent requests:** 10 per city
- **Cities:** 1,000

**Without stampede prevention:**
- API calls: 100,000
- Cost: $100/day = $36,500/year

**With stampede prevention:**
- API calls: 10,000 (90% reduction)
- Cost: $10/day = $3,650/year
- **Savings: $32,850/year** 💰

## Summary

| Aspect | Value |
|--------|-------|
| **Problem** | Multiple concurrent requests → Multiple API calls |
| **Solution** | Distributed locking → Only 1 API call |
| **Benefit** | 90%+ API call reduction |
| **Cost** | Minimal (lock overhead ~1-5ms) |
| **Complexity** | Medium (requires distributed lock) |
| **When to use** | High-traffic, expensive operations |

---

**Remember:** Stampede prevention is about **coordination**, not **speed**. The first request is slower (acquires lock, fetches data), but overall system efficiency improves dramatically! 🚀
