from fastapi.testclient import TestClient

from semantic_cache.api import create_app
from semantic_cache.catalog import FaqCatalog, FaqEntry
from semantic_cache.service import FaqAnswerService

from .fakes import InMemorySemanticCache, KeywordEmbedder


def test_similar_questions_progress_from_miss_to_semantic_to_exact():
    embedder = KeywordEmbedder()
    catalog = FaqCatalog(
        entries=[
            FaqEntry(
                question="What deployment options do I have for ElastiCache?",
                answer=(
                    "ElastiCache offers serverless and node-based deployment "
                    "options."
                ),
                provider="Amazon ElastiCache",
                source_file="aws-elasticache-faq.md",
                section="General",
            ),
            FaqEntry(
                question="How many nodes can I provision?",
                answer="OCI Cache supports both non-sharded and sharded clusters.",
                provider="OCI Cache",
                source_file="oci-cache-faq.md",
                section="Configuration",
            ),
        ],
        corpus_version="test-corpus-v1",
        embedder=embedder,
        similarity_threshold=0.50,
    )
    cache = InMemorySemanticCache(
        embedder=embedder,
        similarity_threshold=0.90,
    )
    service = FaqAnswerService(catalog=catalog, cache=cache, embedder=embedder)
    client = TestClient(create_app(service))

    first = client.post(
        "/ask",
        json={"question": "What deployment choices does ElastiCache provide?"},
    )
    second = client.post(
        "/ask",
        json={"question": "Which ways can I deploy Amazon ElastiCache?"},
    )
    third = client.post(
        "/ask",
        json={"question": "Which ways can I deploy Amazon ElastiCache?"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 200
    assert [
        first.json()["cache"]["type"],
        second.json()["cache"]["type"],
        third.json()["cache"]["type"],
    ] == ["miss", "semantic", "exact"]
    assert second.json()["cache"]["matched_question"] == (
        "What deployment choices does ElastiCache provide?"
    )
    assert first.json()["answer"] == second.json()["answer"] == third.json()["answer"]
    assert second.headers["X-Semantic-Cache-Type"] == "semantic"

    provider_change = client.post(
        "/ask",
        json={"question": "How many nodes does OCI Cache support?"},
    )

    assert provider_change.status_code == 200
    assert provider_change.json()["cache"]["type"] == "miss"
    assert provider_change.json()["source"]["provider"] == "OCI Cache"


def test_unknown_question_returns_suggestions_without_caching_an_answer():
    embedder = KeywordEmbedder()
    catalog = FaqCatalog(
        entries=[
            FaqEntry(
                question="How does Memorystore monitor CPU usage?",
                answer="Use the maximum CPU utilization metric.",
                provider="Google Cloud Memorystore",
                source_file="gcp-memorystore-valkey-faq.md",
                section="Monitoring",
            )
        ],
        corpus_version="test-corpus-v1",
        embedder=embedder,
        similarity_threshold=0.80,
    )
    cache = InMemorySemanticCache(embedder=embedder)
    client = TestClient(
        create_app(
            FaqAnswerService(catalog=catalog, cache=cache, embedder=embedder)
        )
    )

    response = client.post(
        "/ask",
        json={"question": "How do I bake sourdough bread?"},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["message"] == (
        "No sufficiently relevant managed-service FAQ was found."
    )
    assert response.json()["detail"]["suggestions"] == [
        "How does Memorystore monitor CPU usage?"
    ]
    assert cache.stats()["answers"] == 0


def test_blank_question_is_rejected_before_the_service_is_called():
    embedder = KeywordEmbedder()
    catalog = FaqCatalog(
        entries=[
            FaqEntry(
                question="What is Valkey?",
                answer="Valkey is an open source in-memory data store.",
                provider="Valkey",
                source_file="valkey-faq.md",
                section="General",
            )
        ],
        corpus_version="test-corpus-v1",
        embedder=embedder,
    )
    cache = InMemorySemanticCache(embedder=embedder)
    client = TestClient(
        create_app(
            FaqAnswerService(catalog=catalog, cache=cache, embedder=embedder)
        )
    )

    response = client.post("/ask", json={"question": "   "})

    assert response.status_code == 422
    assert cache.stats()["answers"] == 0
