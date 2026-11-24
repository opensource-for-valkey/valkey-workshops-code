"""Opt-in checks against an authenticated Valkey 9.2 Bundle, without ML models."""

from datetime import datetime, timedelta, timezone
import importlib
import os
from pathlib import Path
import sys
import time
import uuid

import numpy as np
import pytest

WORKSHOPS = Path(__file__).resolve().parents[2]
for project in ("python-common", "semantic-faq", "genai-weather"):
    sys.path.insert(0, str(WORKSHOPS / project))

from valkey_client_manager import ValkeyClientManager, search_document_keys

pytestmark = pytest.mark.skipif(
    os.getenv("VALKEY_LEGACY_INTEGRATION") != "1",
    reason="Set VALKEY_LEGACY_INTEGRATION=1 and configure the authenticated bundle",
)


class FakeEmbedder:
    dimension = 2
    model_name = "workshop-test"

    def embed(self, _text):
        return np.asarray([1, 0], dtype=np.float32)


@pytest.fixture
def client():
    with ValkeyClientManager(default_port=16379) as manager:
        yield manager.client


def isolate(monkeypatch, module):
    prefix = "workshop:legacy-test:" + uuid.uuid4().hex
    for name, suffix in (
        ("CACHE_PREFIX", ""),
        ("ANSWER_PREFIX", ":answer"),
        ("PROMPT_PREFIX", ":prompt"),
        ("EMBEDDING_PREFIX", ":embedding"),
    ):
        monkeypatch.setattr(module, name, prefix + suffix)
    monkeypatch.setattr(module, "INDEX_NAME", "legacy_test_" + uuid.uuid4().hex)


def await_index(client, index, vector):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if search_document_keys(client, index, vector, 3):
            return
        time.sleep(0.1)
    raise AssertionError("HNSW index did not expose the stored record")


def drop_index(client, index):
    client.custom_command(["FT.DROPINDEX", index])


def test_json_roundtrip_ttl_and_namespaced_clear(client):
    from openweathermap_api.cache import ValkeyJsonCache

    prefix = "workshop:legacy-json-test:" + uuid.uuid4().hex
    cache = ValkeyJsonCache(client, ttl_seconds=60, key_prefix=prefix)
    key = prefix + ":response"
    try:
        assert cache.get(key) is None
        cache.set(key, {"temperature": 21, "units": "metric"})
        assert cache.get(key) == {"temperature": 21, "units": "metric"}
        assert 0 < client.ttl(key) <= 60
        assert cache.clear() == 1
        assert cache.get(key) is None
    finally:
        client.unlink([key])


def test_faq_exact_and_indexed_semantic_scope_and_corpus_gates(client, monkeypatch):
    from semantic_cache.models import CachedAnswer

    module = importlib.import_module("semantic_cache.cache")
    isolate(monkeypatch, module)
    cache = module.ValkeySemanticCache(client, FakeEmbedder(), ttl_seconds=60)
    answer = CachedAnswer("Answer", "Source?", "AWS", "aws.md", "Basics", 0.9, "v1")
    vector = FakeEmbedder().embed("")
    try:
        cache.store("question a", "Question A?", answer, vector, "aws")
        assert cache.lookup("question a", "v1", "aws").lookup.cache_type == "exact"
        cache._ensure_index()
        await_index(client, module.INDEX_NAME, vector.tobytes())
        assert cache.lookup("question b", "v1", "aws").lookup.cache_type == "semantic"
        assert cache.lookup("question b", "v1", "gcp").lookup is None
        assert cache.lookup("question b", "v2", "aws").lookup is None
    finally:
        cache.clear()
        drop_index(client, module.INDEX_NAME)


def test_weather_indexed_semantic_rejects_different_time_window(client, monkeypatch):
    from cache_me_if_you_can_genai.models import Location, WeatherIntent

    module = importlib.import_module("cache_me_if_you_can_genai.cache")
    isolate(monkeypatch, module)
    cache = module.SemanticWeatherCache(client, FakeEmbedder(), ttl_seconds=60)
    start = datetime(2026, 11, 23, tzinfo=timezone.utc)
    location = Location(
        "buenos-aires-ar",
        "Buenos Aires",
        "AR",
        -34.6,
        -58.4,
        "America/Argentina/Buenos_Aires",
        ("buenos aires",),
    )
    intent = WeatherIntent(
        "Weather today?",
        "question a",
        location,
        start,
        start + timedelta(days=1),
        "daily",
        "today",
        "metric",
    )
    vector = FakeEmbedder().embed("")
    try:
        cache.store("question a", "Weather today?", intent, {"prose": "Answer"}, vector)
        assert cache.get_exact("question a").cache_type == "exact"
        cache._ensure_index()
        await_index(client, module.INDEX_NAME, vector.tobytes())
        assert cache.find_semantic("question b", intent).lookup.cache_type == "semantic"
        later = WeatherIntent(
            "Tomorrow?",
            "question c",
            location,
            start + timedelta(days=1),
            start + timedelta(days=2),
            "daily",
            "tomorrow",
            "metric",
        )
        assert cache.find_semantic("question c", later).lookup is None
    finally:
        cache.clear()
        drop_index(client, module.INDEX_NAME)
