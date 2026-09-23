from __future__ import annotations

from dataclasses import replace
import hashlib

import numpy as np

from semantic_cache.models import CacheLookup, CacheProbe, CachedAnswer


class KeywordEmbedder:
    """Deterministic embeddings for HTTP behavior tests."""

    dimension = 4
    model_name = "keyword-test-embedder"

    def embed(self, text: str) -> np.ndarray:
        normalized = text.casefold()
        vector = np.array(
            [
                float(any(word in normalized for word in ("deploy", "deployment", "ways", "choices"))),
                float(any(word in normalized for word in ("cpu", "utilization", "monitor"))),
                float(any(word in normalized for word in ("bread", "bake", "sourdough"))),
                0.1,
            ],
            dtype=np.float32,
        )
        return vector / np.linalg.norm(vector)

    def embed_many(self, texts: list[str]) -> np.ndarray:
        return np.vstack([self.embed(text) for text in texts])


class InMemorySemanticCache:
    def __init__(
        self,
        *,
        embedder: KeywordEmbedder,
        similarity_threshold: float = 0.90,
    ) -> None:
        self.embedder = embedder
        self.similarity_threshold = similarity_threshold
        self.exact: dict[str, CachedAnswer] = {}
        self.semantic: dict[
            str,
            tuple[str, str, np.ndarray, CachedAnswer],
        ] = {}

    def lookup(
        self,
        normalized_question: str,
        corpus_version: str,
        scope: str,
    ) -> CacheProbe:
        exact = self.exact.get(normalized_question)
        if exact is not None and exact.corpus_version == corpus_version:
            return CacheProbe(
                embedding=None,
                lookup=CacheLookup(answer=exact, cache_type="exact"),
            )

        embedding = self.embedder.embed(normalized_question)
        best: tuple[float, str, CachedAnswer] | None = None
        for (
            original_question,
            stored_scope,
            stored_embedding,
            answer,
        ) in self.semantic.values():
            if answer.corpus_version != corpus_version:
                continue
            if stored_scope != scope:
                continue
            similarity = float(np.dot(embedding, stored_embedding))
            if best is None or similarity > best[0]:
                best = (similarity, original_question, answer)

        if best is not None and best[0] >= self.similarity_threshold:
            return CacheProbe(
                embedding=embedding,
                lookup=CacheLookup(
                    answer=best[2],
                    cache_type="semantic",
                    matched_question=best[1],
                    similarity=best[0],
                ),
            )
        return CacheProbe(embedding=embedding, lookup=None)

    def store(
        self,
        normalized_question: str,
        original_question: str,
        answer: CachedAnswer,
        embedding: np.ndarray,
        scope: str,
    ) -> str:
        key = hashlib.sha256(normalized_question.encode()).hexdigest()
        self.exact[normalized_question] = answer
        self.semantic[key] = (original_question, scope, embedding, answer)
        return f"semantic-faq-cache:v1:embedding:{key}"

    def link_exact(
        self,
        normalized_question: str,
        answer: CachedAnswer,
    ) -> str:
        self.exact[normalized_question] = replace(answer)
        return f"semantic-faq-cache:v1:prompt:{hashlib.sha256(normalized_question.encode()).hexdigest()}"

    def stats(self) -> dict[str, int]:
        return {
            "answers": len({answer.answer for answer in self.exact.values()}),
            "exact_questions": len(self.exact),
            "embeddings": len(self.semantic),
        }

    def clear(self) -> int:
        count = len(self.exact) + len(self.semantic)
        self.exact.clear()
        self.semantic.clear()
        return count

    def ping(self) -> bool:
        return True
