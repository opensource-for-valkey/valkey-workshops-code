from datetime import datetime, timedelta
import json
import os
import secrets
import time

from flask import Flask, session
from glide_sync import ListDirection, RequestError, ServerCredentials
import numpy as np
import pytest
from sqlalchemy import text

from core import get_cache_client
from core.semantic_search import SemanticSearch
from daos.cache_aside import CacheAside
from daos.semantic_cache import SemanticSQLCache
from daos.weather_api_cache import WeatherAPICache
from daos.write_behind_cache import WriteBehindCache
from daos.write_through_cache import WriteThroughCache
from session_demo.glide_session import GlideSessionInterface
from valkey_client_manager import ValkeyClientManager


def test_native_cache_expiry_and_scoped_clear(cache):
    sentinel = cache.prefix.removesuffix(":") + "-outside"
    cache.client.set(sentinel, "keep")
    try:
        assert cache.set("value", "cached", ttl=1)
        assert cache.get("value") == "cached"
        assert cache.client.ttl(cache.key("value")) in {0, 1}
        time.sleep(1.1)
        assert cache.get("value") is None
        cache.set("another", "value")
        assert cache.flush_all() == 1
        assert cache.client.get(sentinel) == b"keep"
    finally:
        cache.client.delete([sentinel])


def test_wrong_native_credentials_fail_visible(cache):
    manager = ValkeyClientManager()
    manager.configuration.credentials = ServerCredentials(
        password=secrets.token_urlsafe(32), username="default"
    )
    try:
        with pytest.raises(RequestError):
            manager.client.ping()
    finally:
        manager.close()


def test_lock_release_checks_owner_and_expiration(cache):
    weather = WeatherAPICache(cache=cache)
    first = weather.acquire_lock("weather", timeout=1)
    assert first
    assert weather.acquire_lock("weather", timeout=1) is None
    assert not weather.release_lock("weather", "wrong-owner")
    time.sleep(1.1)
    second = weather.acquire_lock("weather", timeout=10)
    assert second and second != first
    assert not weather.release_lock("weather", first)
    assert weather.release_lock("weather", second)

def test_fractional_lock_ttl_is_native_milliseconds(cache):
    weather = WeatherAPICache(cache=cache)
    token = weather.acquire_lock("short", timeout=0.05)
    assert token
    assert 0 <= cache.client.pttl(cache.key("lock:short")) <= 50
    assert weather.release_lock("short", token)


def test_stampede_metrics_do_not_claim_success_for_errors():
    from samples.demo_stampede_prevention import StampedeMetrics

    assert not StampedeMetrics(total_requests=4, errors=4).stampede_prevented
    assert StampedeMetrics(total_requests=4, cache_hits=3, cache_misses=1, api_calls=1).stampede_prevented


def test_cache_aside_database_result_and_empty_result(cache, database):
    dao = CacheAside(db_engine=database, cache=cache)
    query = "SELECT flight_id, flightno FROM flight WHERE flight_id = 1"
    rows, source, _ = dao.execute_query(query)
    assert source == "CACHE_MISS" and rows[0]["flightno"] == "WS001"
    assert dao.execute_query(query)[:2] == (rows, "CACHE_HIT")
    assert dao.invalidate_query(query)
    assert dao.execute_query(query)[1] == "CACHE_MISS"
    missing = "SELECT flight_id FROM flight WHERE flight_id = -1"
    assert dao.execute_query(missing)[0] == []


def test_write_through_commits_database_and_refreshes_native_cache(cache, database):
    dao = WriteThroughCache(db_engine=database, cache=cache)
    original = dao.get_flight(1)[0]
    assert original["flightno"] == "WS001"
    departure = datetime(2026, 11, 23, 11)
    arrival = departure + timedelta(hours=2)
    success, queries = dao.update_flight_departure(1, departure, arrival)
    assert success and len(queries) == 3
    stored = json.loads(cache.get("flight:1"))
    assert stored["departure"].startswith("2026-11-23 11:00")
    with database.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM flight_log")).scalar() == 1


def test_write_behind_atomic_publish_recovery_and_dead_letter(cache, database):
    dao = WriteBehindCache(db_engine=database, cache=cache, max_retries=2)
    assert dao.get_flight(1)[0]["flightno"] == "WS001"
    departure = datetime(2026, 11, 23, 13)
    assert dao.update_flight_departure(1, departure, departure + timedelta(hours=2))[0]
    assert json.loads(cache.get("flight:1"))["departure"] == departure.isoformat()
    assert dao.get_queue_length() == 1
    # Simulate a worker stopping after its atomic claim, before database commit.
    claimed = cache.client.lmove(
        dao.QUEUE_KEY, dao.PROCESSING_KEY, ListDirection.LEFT, ListDirection.RIGHT
    )
    assert claimed and cache.client.llen(dao.PROCESSING_KEY) == 1
    assert dao.recover_processing_tasks() == 1
    processed, failed, _ = dao.process_queue()
    assert (processed, failed) == (1, 0)
    assert dao.get_queue_length() == 0
    with database.connect() as connection:
        assert connection.execute(text("SELECT departure FROM flight")).scalar().startswith("2026-11-23 13:00")
    cache.client.rpush(dao.QUEUE_KEY, ['{"flight_id":999}'])
    assert dao.process_queue(batch_size=1)[1] == 1
    assert dao.process_queue(batch_size=1)[1] == 1
    assert dao.get_dead_letter_length() == 1


def test_flask_signed_id_shared_state_rotation_tamper_and_expiration(cache):
    secret = secrets.token_urlsafe(32)

    def make_app():
        app = Flask(__name__)
        app.secret_key = secret
        app.session_interface = GlideSessionInterface(cache, ttl=1)

        @app.route("/write")
        def write():
            session["weather"] = {"city": "London", "temp": 12}
            session["flights"] = [{"flight_id": 1}]
            return "saved"

        @app.route("/read")
        def read():
            return {"weather": session.get("weather"), "flights": session.get("flights", [])}

        @app.route("/logout")
        def logout():
            session.clear()
            app.session_interface.regenerate(session)
            return "logged out"

        return app

    first_app, second_app = make_app(), make_app()
    first, second = first_app.test_client(), second_app.test_client()
    first.get("/write")
    original_cookie = first.get_cookie("session").value
    second.set_cookie("session", original_cookie)
    assert second.get("/read").json["weather"]["city"] == "London"
    sid = first_app.session_interface._signer(first_app).loads(original_cookie)
    key = first_app.session_interface._key(sid)
    assert cache.client.ttl(key) in {0, 1}
    first.get("/logout")
    assert cache.client.get(key) is None
    second.set_cookie("session", original_cookie + "tampered")
    assert second.get("/read").json == {"weather": None, "flights": []}
    first.get("/write")
    expiring_cookie = first.get_cookie("session").value
    expiring_sid = first_app.session_interface._signer(first_app).loads(expiring_cookie)
    time.sleep(1.1)
    first.set_cookie("session", expiring_cookie)
    assert first.get("/read").json["weather"] is None
    assert cache.client.get(first_app.session_interface._key(expiring_sid)) is None


def test_semantic_native_hash_scan_fallback_without_model_download(cache):
    search = SemanticSearch(valkey_client=cache.client, verbose=False)
    assert search._embedding_model is None
    vector = np.array([1, 0, 0], dtype=np.float32)
    key = cache.key("embedding:one")
    cache.client.hset(key, {"embedding": vector.tobytes(), "prompt": "flights", "query_key": "query"})
    matches = search._brute_force_search(vector, cache.key("embedding:"), k=1)
    assert matches[0]["prompt"] == "flights"
    assert matches[0]["similarity"] == pytest.approx(1.0)

def test_semantic_exact_hit_avoids_model_and_ollama(cache, monkeypatch):
    # The vector connection can use the base server for the exact-hit path.
    monkeypatch.setenv("VECTOR_HOST", cache.host)
    monkeypatch.setenv("VECTOR_PORT", str(cache.port))
    dao = SemanticSQLCache(verbose=False)
    prompt = "show flights"
    semantic_key = f"{cache.prefix}semantic:prompt:{dao._hash_text(prompt)}"
    query_key = f"{cache.prefix}db:query:one"
    dao.valkey_client.set(query_key, '{"sql":"SELECT flight_id FROM flight"}')
    dao.valkey_client.set(semantic_key, query_key)
    try:
        result = dao.get_or_generate_sql(prompt, verbose=False)
        assert result["cache_type"] == "exact"
        assert result["sql"] == "SELECT flight_id FROM flight"
        assert dao.semantic_search._embedding_model is None
    finally:
        dao.close()


def test_bundle_native_vector_search_without_model(cache, monkeypatch):
    if not os.getenv("VECTOR_PORT"):
        pytest.skip("Configure the authenticated Valkey Search bundle")
    monkeypatch.setenv("EMBEDDING_DIM", "3")
    manager = ValkeyClientManager(env_prefix="VECTOR", fallback_prefix="VALKEY")
    search = SemanticSearch(valkey_client=manager.client)
    index = cache.prefix + "vector-index"
    key = cache.prefix + "vector:one"
    vector = np.array([1, 0, 0], dtype=np.float32)
    try:
        assert search.create_vector_index(index, cache.prefix + "vector:")
        manager.client.hset(
            key, {"embedding": vector.tobytes(), "prompt": "flights", "query_key": "one"}
        )
        matches = []
        for _ in range(30):
            matches = search.search_similar(vector, index, cache.prefix + "vector:", k=1)
            if matches:
                break
            time.sleep(0.1)
        assert matches[0]["prompt"] == "flights"
        assert matches[0]["similarity"] == pytest.approx(1.0)
        assert search._embedding_model is None
    finally:
        search.drop_index(index)
        manager.client.delete([key])
        manager.close()


def test_prefix_validation_rejects_globs(monkeypatch):
    monkeypatch.setenv("CACHE_KEY_PREFIX", "baseline:*:")
    with pytest.raises(ValueError):
        get_cache_client()
