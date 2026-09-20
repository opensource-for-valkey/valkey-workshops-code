"""Isolated unit tests for weather-cache stampede prevention."""

import fnmatch
import json

import pytest

from daos.weather_api_cache import WeatherAPICache


class FakeClient:
    def __init__(self):
        self.values = {}
        self.closed = False

    def ping(self):
        return True

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def setex(self, key, ttl, value):
        self.values[key] = value
        return True

    def get(self, key):
        return self.values.get(key)

    def delete(self, key):
        return int(self.values.pop(key, None) is not None)

    def eval(self, script, numkeys, key, token):
        if self.values.get(key) != token:
            return 0
        return self.delete(key)

    def keys(self, pattern):
        return [key for key in self.values if fnmatch.fnmatch(key, pattern)]

    def flushdb(self):
        self.values.clear()

    def close(self):
        self.closed = True


class FakeCache:
    cache_type = "valkey"
    host = "fake"
    port = 0

    def __init__(self, fail_get=False):
        self.client = FakeClient()
        self.fail_get = fail_get

    def get(self, key):
        if self.fail_get:
            raise ConnectionError("cache unavailable")
        return self.client.get(key)

    def set(self, key, value, ttl=None):
        return self.client.setex(key, ttl, value)

    def delete(self, key):
        return bool(self.client.delete(key))

    def flush_all(self):
        self.client.flushdb()

    def close(self):
        self.client.close()


def test_lock_acquisition_and_release():
    cache = WeatherAPICache(cache=FakeCache())
    key = "test:lock:key"

    token = cache.acquire_lock(key, timeout=5)
    assert token
    assert not cache.acquire_lock(key, timeout=5)
    assert cache.release_lock(key, token)
    assert cache.acquire_lock(key, timeout=5)


def test_expired_owner_cannot_release_new_owners_lock():
    cache = WeatherAPICache(cache=FakeCache())
    key = "test:lock:ownership"
    lock_key = f"lock:{key}"

    first_token = cache.acquire_lock(key, timeout=5)
    cache.client.delete(lock_key)  # Simulate lock expiry.
    second_token = cache.acquire_lock(key, timeout=5)

    assert first_token != second_token
    assert not cache.release_lock(key, first_token)
    assert cache.client.get(lock_key) == second_token


def test_cache_operations():
    cache = WeatherAPICache(cache=FakeCache())
    key = "test:weather:us:12345"
    data = {"temp": 72.5, "condition": "sunny"}

    assert cache.set(key, data, ttl=60)
    assert cache.get(key) == data
    assert cache.delete(key)
    assert cache.get(key) is None


def test_double_check_pattern():
    cache = WeatherAPICache(cache=FakeCache())
    key = "test:weather:us:54321"
    data = {"temp": 68.0, "condition": "cloudy"}

    token = cache.acquire_lock(key, timeout=5)
    assert token
    cache.set(key, data, ttl=60)
    assert cache.release_lock(key, token)
    assert cache.get(key) == data


def test_transport_failure_is_not_reported_as_a_cache_miss():
    cache = WeatherAPICache(cache=FakeCache(fail_get=True), ping=False)

    with pytest.raises(ConnectionError, match="cache unavailable"):
        cache.get("weather:unavailable")
