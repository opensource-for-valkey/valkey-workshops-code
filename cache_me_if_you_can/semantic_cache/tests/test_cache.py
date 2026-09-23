from fnmatch import fnmatch

import numpy as np

from semantic_cache.cache import ValkeySemanticCache
from semantic_cache.models import CachedAnswer


class FixedEmbedder:
    dimension = 3
    model_name = "fixed-test-embedder"

    def embed(self, text: str) -> np.ndarray:
        if "deployment" in text or "deploy" in text:
            return np.array([1.0, 0.01, 0.0], dtype=np.float32)
        return np.array([0.0, 1.0, 0.01], dtype=np.float32)


class MemoryPipeline:
    def __init__(self, client: "MemoryValkey") -> None:
        self.client = client
        self.operations: list[tuple[str, str, object]] = []

    def setex(self, key: str, _ttl: int, value: object) -> "MemoryPipeline":
        self.operations.append(("set", key, value))
        return self

    def hset(self, key: str, *, mapping: object) -> "MemoryPipeline":
        self.operations.append(("hset", key, mapping))
        return self

    def expire(self, _key: str, _ttl: int) -> "MemoryPipeline":
        return self

    def execute(self) -> list[bool]:
        for operation, key, value in self.operations:
            target = (
                self.client.strings
                if operation == "set"
                else self.client.hashes
            )
            target[key] = value
        return [True] * len(self.operations)


class MemoryValkey:
    def __init__(self) -> None:
        self.strings: dict[str, object] = {}
        self.hashes: dict[str, object] = {}

    def pipeline(self, *, transaction: bool) -> MemoryPipeline:
        assert transaction is True
        return MemoryPipeline(self)

    def get(self, key: str) -> object | None:
        return self.strings.get(key)

    def hgetall(self, key: str) -> object:
        return self.hashes.get(key, {})

    def scan_iter(self, *, match: str, count: int):
        assert count == 100
        for key in [*self.strings, *self.hashes]:
            if fnmatch(key, match):
                yield key

    def unlink(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            removed += int(self.strings.pop(key, None) is not None)
            removed += int(self.hashes.pop(key, None) is not None)
        return removed

    def ping(self) -> bool:
        return True


def test_valkey_cache_promotes_semantic_hits_and_enforces_constraints():
    client = MemoryValkey()
    cache = ValkeySemanticCache(
        client,
        FixedEmbedder(),
        ttl_seconds=60,
        similarity_threshold=0.88,
    )
    answer = CachedAnswer(
        answer="Serverless and node-based deployments are available.",
        source_question="What deployment options do I have for ElastiCache?",
        provider="Amazon ElastiCache",
        source_file="aws-elasticache-faq.md",
        section="General",
        retrieval_similarity=0.93,
        corpus_version="corpus-v1",
    )

    first = cache.lookup(
        "what deployment choices does elasticache provide?",
        "corpus-v1",
        "aws-elasticache-faq.md",
    )
    assert first.lookup is None
    cache.store(
        "what deployment choices does elasticache provide?",
        "What deployment choices does ElastiCache provide?",
        answer,
        first.embedding,
        "aws-elasticache-faq.md",
    )

    semantic = cache.lookup(
        "which deployment options are available for amazon elasticache?",
        "corpus-v1",
        "aws-elasticache-faq.md",
    )
    assert semantic.lookup is not None
    assert semantic.lookup.cache_type == "semantic"
    cache.link_exact(
        "which deployment options are available for amazon elasticache?",
        semantic.lookup.answer,
    )

    exact = cache.lookup(
        "which deployment options are available for amazon elasticache?",
        "corpus-v1",
        "aws-elasticache-faq.md",
    )
    wrong_provider = cache.lookup(
        "which deployment options are available for oci cache?",
        "corpus-v1",
        "oci-cache-faq.md",
    )
    changed_corpus = cache.lookup(
        "which deployment options are available for amazon elasticache?",
        "corpus-v2",
        "aws-elasticache-faq.md",
    )

    assert exact.lookup is not None
    assert exact.lookup.cache_type == "exact"
    assert wrong_provider.lookup is None
    assert changed_corpus.lookup is None
