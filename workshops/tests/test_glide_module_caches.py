"""Real JSON/vector-module checks for the existing Python workshop migrations."""

from datetime import datetime, timedelta, timezone
import importlib
import os
from pathlib import Path
import time
from uuid import uuid4

import pytest


WORKSHOPS = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(
    os.environ.get("VALKEY_MODULES_INTEGRATION") != "1",
    reason="Opt in to an isolated Valkey bundle with VALKEY_MODULES_INTEGRATION=1",
)


@pytest.fixture
def runtime(monkeypatch):
    for folder in ("python-common", "semantic-faq", "genai-weather"):
        monkeypatch.syspath_prepend(str(WORKSHOPS / folder))
    from dotenv import dotenv_values
    from valkey_client_manager import ValkeyClientManager, scan_keys

    if path := os.environ.get("WORKSHOP_ENV_FILE"):
        for name, value in dotenv_values(path).items():
            if value is not None:
                monkeypatch.setenv(name, value)
    namespace = f"review:{uuid4().hex}"
    indexes = []
    with ValkeyClientManager() as manager:
        client = manager.client
        assert client.ping() == b"PONG"
        yield client, namespace, indexes
        for index in indexes:
            client.custom_command(["FT.DROPINDEX", index])
        keys = list(scan_keys(client, f"{namespace}:*"))
        if keys:
            client.unlink(keys)


def configure_cache(monkeypatch, module, namespace, indexes):
    """Keep keys and Search indexes private to this individual test."""
    prefix = f"{namespace}:{module.__name__.split('.')[0]}"
    for name, suffix in (
        ("CACHE_PREFIX", ""),
        ("ANSWER_PREFIX", ":answer"),
        ("PROMPT_PREFIX", ":prompt"),
        ("EMBEDDING_PREFIX", ":embedding"),
    ):
        monkeypatch.setattr(module, name, prefix + suffix)
    index = f"review_{uuid4().hex}"
    monkeypatch.setattr(module, "INDEX_NAME", index)
    return index


class DeterministicEmbedder:
    dimension = 2
    model_name = "integration-fixture"

    def embed(self, _text):
        import numpy as np

        return np.array([1, 0], dtype=np.float32)


def wait_for_index(client, index, key, embedding):
    """Require the actual Search index to return the record, not scan fallback."""
    from valkey_client_manager import search_document_keys

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if key.encode() in search_document_keys(client, index, embedding.tobytes(), 10):
            return
        time.sleep(0.05)
    pytest.fail("The native vector Search index did not return the stored record")


def test_json_glide_transaction_ttl_and_scoped_clear(runtime):
    client, namespace, _ = runtime
    cache_module = importlib.import_module("openweathermap_api.cache")
    prefix = f"{namespace}:response"
    cache = cache_module.ValkeyJsonCache(client, ttl_seconds=30, key_prefix=prefix)
    key = cache_module.build_cache_key(
        "onecall", {"lat": -34.6, "lon": -58.38, "appid": "exclude-me"},
        key_prefix=prefix,
    )
    payload = {"current": {"temp": 22.5}}
    assert "exclude-me" not in key
    cache.set(key, payload)
    assert cache.get(key) == payload
    assert 0 < client.ttl(key) <= 30
    other = f"{namespace}:outside:keep"
    client.set(other, "keep")
    assert cache.clear() == 1
    assert cache.get(key) is None
    assert client.get(other) == b"keep"


def test_faq_glide_exact_indexed_semantic_and_constraints(runtime, monkeypatch):
    import numpy as np
    from semantic_cache.models import CachedAnswer

    client, namespace, indexes = runtime
    module = importlib.import_module("semantic_cache.cache")
    index = configure_cache(monkeypatch, module, namespace, indexes)
    cache = module.ValkeySemanticCache(client, DeterministicEmbedder(), ttl_seconds=30)
    answer = CachedAnswer(
        "Use native data structures", "What should I use?", "fixture",
        "fixture.md", "Architecture", 1.0, "corpus-v1",
    )
    embedding = np.array([1, 0], dtype=np.float32)
    key = cache.store("original", "What should I use?", answer, embedding, "scope-a")
    assert cache.lookup("original", "corpus-v1", "scope-a").lookup.cache_type == "exact"
    cache._ensure_index()
    indexes.append(index)
    wait_for_index(client, index, key, embedding)
    probe = cache.lookup("paraphrase", "corpus-v1", "scope-a")
    assert probe.lookup.cache_type == "semantic"
    assert probe.lookup.similarity == 1.0
    assert cache.lookup("paraphrase", "corpus-v2", "scope-a").lookup is None
    assert cache.lookup("paraphrase", "corpus-v1", "scope-b").lookup is None
    assert cache.clear() == 3


def test_weather_glide_indexed_reuse_respects_time_window(runtime, monkeypatch):
    import numpy as np
    from cache_me_if_you_can_genai.models import Location, WeatherIntent

    client, namespace, indexes = runtime
    module = importlib.import_module("cache_me_if_you_can_genai.cache")
    index = configure_cache(monkeypatch, module, namespace, indexes)
    location = Location(
        "review-ar", "Buenos Aires", "Argentina", -34.6, -58.38,
        "America/Argentina/Buenos_Aires", (),
    )
    start = datetime(2026, 11, 23, tzinfo=timezone.utc)
    intent = WeatherIntent(
        "Weather?", "weather", location, start, start + timedelta(days=1),
        "daily", "today", "metric",
    )
    cache = module.SemanticWeatherCache(client, DeterministicEmbedder(), ttl_seconds=30)
    answer = {"summary": "Sunny", "temp": 22.5}
    embedding = np.array([1, 0], dtype=np.float32)
    cache.store("original", "Weather?", intent, answer, embedding)
    assert cache.get_exact("original").answer == answer
    cache._ensure_index()
    indexes.append(index)
    key = f"{module.EMBEDDING_PREFIX}:{cache._digest('original')}"
    wait_for_index(client, index, key, embedding)
    probe = cache.find_semantic("paraphrase", intent)
    assert probe.lookup.cache_type == "semantic"
    assert probe.lookup.answer == answer
    tomorrow = WeatherIntent(
        "Tomorrow?", "tomorrow", location, start + timedelta(days=1),
        start + timedelta(days=2), "daily", "tomorrow", "metric",
    )
    assert cache.find_semantic("paraphrase", tomorrow).lookup is None
    assert cache.clear() == 3
