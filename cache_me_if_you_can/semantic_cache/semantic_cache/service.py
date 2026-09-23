from __future__ import annotations

import logging
import re
from threading import Lock
from time import perf_counter
from typing import Any, Protocol

from .catalog import FaqCatalog
from .models import AnswerResult, CacheProbe, CachedAnswer, Embedder


LOGGER = logging.getLogger(__name__)


class SemanticCache(Protocol):
    def lookup(
        self,
        normalized_question: str,
        corpus_version: str,
        scope: str,
    ) -> CacheProbe: ...

    def store(
        self,
        normalized_question: str,
        original_question: str,
        answer: CachedAnswer,
        embedding: Any,
        scope: str,
    ) -> str: ...

    def link_exact(
        self,
        normalized_question: str,
        answer: CachedAnswer,
    ) -> str: ...

    def stats(self) -> dict[str, int]: ...

    def clear(self) -> int: ...

    def ping(self) -> bool: ...


class QuestionNotFoundError(LookupError):
    def __init__(self, suggestions: list[str]) -> None:
        super().__init__("No sufficiently relevant managed-service FAQ was found.")
        self.suggestions = suggestions


def normalize_question(question: str) -> str:
    normalized = " ".join(question.strip().casefold().split())
    if not normalized:
        raise ValueError("question must not be empty")
    return re.sub(r"\s+([?.!,])", r"\1", normalized)


SCOPES = (
    (("elasticache", "amazon", "aws"), "aws-elasticache-faq.md"),
    (("memorystore", "google cloud", "gcp"), "gcp-memorystore-valkey-faq.md"),
    (("heroku",), "heroku-key-value-store-faq.md"),
    (("momento",), "momento-cache-faq.md"),
    (("oci", "oracle"), "oci-cache-faq.md"),
)


def detect_scope(normalized_question: str) -> str:
    for aliases, source_file in SCOPES:
        if any(alias in normalized_question for alias in aliases):
            return source_file
    return "global"


class FaqAnswerService:
    """Answer FAQ questions through exact, semantic, and retrieval paths."""

    def __init__(
        self,
        *,
        catalog: FaqCatalog,
        cache: SemanticCache,
        embedder: Embedder,
    ) -> None:
        self.catalog = catalog
        self.cache = cache
        self.embedder = embedder
        self._metrics = {
            "requests": 0,
            "exact_hits": 0,
            "semantic_hits": 0,
            "misses": 0,
            "cache_bypasses": 0,
            "cache_errors": 0,
            "embedding_calls": 0,
            "faq_retrievals": 0,
        }
        self._lock = Lock()

    def answer(self, question: str) -> AnswerResult:
        started = perf_counter()
        normalized = normalize_question(question)
        scope = detect_scope(normalized)
        self._increment("requests")

        probe: CacheProbe | None = None
        cache_available = True
        try:
            probe = self.cache.lookup(
                normalized,
                self.catalog.corpus_version,
                scope,
            )
            if probe.embedding is not None:
                self._increment("embedding_calls")
        except Exception as error:
            cache_available = False
            self._cache_error("lookup", error)

        if probe is not None and probe.lookup is not None:
            lookup = probe.lookup
            if lookup.cache_type == "semantic":
                try:
                    self.cache.link_exact(normalized, lookup.answer)
                except Exception as error:
                    self._cache_error("exact promotion", error)
                self._increment("semantic_hits")
            else:
                self._increment("exact_hits")
            return self._result(
                question=question,
                normalized=normalized,
                answer=lookup.answer,
                cache_type=lookup.cache_type,
                cache_key=lookup.cache_key,
                cache_similarity=lookup.similarity,
                matched_question=lookup.matched_question,
                started=started,
            )

        embedding = probe.embedding if probe is not None else None
        if embedding is None:
            embedding = self.embedder.embed(normalized)
            self._increment("embedding_calls")

        self._increment("faq_retrievals")
        search = self.catalog.search(
            normalized,
            embedding=embedding,
            source_file=None if scope == "global" else scope,
        )
        if search.match is None:
            raise QuestionNotFoundError(
                [match.entry.question for match in search.suggestions]
            )

        match = search.match
        answer = CachedAnswer(
            answer=match.entry.answer,
            source_question=match.entry.question,
            provider=match.entry.provider,
            source_file=match.entry.source_file,
            section=match.entry.section,
            retrieval_similarity=match.similarity,
            corpus_version=self.catalog.corpus_version,
        )
        cache_type = "miss" if cache_available else "bypass"
        cache_key = None
        if cache_available:
            try:
                cache_key = self.cache.store(
                    normalized,
                    question,
                    answer,
                    embedding,
                    scope,
                )
            except Exception as error:
                cache_type = "bypass"
                self._cache_error("store", error)

        self._increment("misses" if cache_type == "miss" else "cache_bypasses")
        return self._result(
            question=question,
            normalized=normalized,
            answer=answer,
            cache_type=cache_type,
            cache_key=cache_key,
            cache_similarity=None,
            matched_question=None,
            started=started,
        )

    def metrics(self) -> dict[str, Any]:
        with self._lock:
            snapshot = dict(self._metrics)
        hits = snapshot["exact_hits"] + snapshot["semantic_hits"]
        snapshot["cache_hits"] = hits
        snapshot["hit_rate"] = (
            round(hits / snapshot["requests"], 4)
            if snapshot["requests"]
            else 0.0
        )
        try:
            snapshot["cache_items"] = self.cache.stats()
        except Exception:
            snapshot["cache_items"] = None
        return snapshot

    def health(self) -> dict[str, Any]:
        try:
            cache_reachable = self.cache.ping()
        except Exception:
            cache_reachable = False
        return {
            "status": "ok" if cache_reachable else "degraded",
            "cache_reachable": cache_reachable,
            "faq_entries": len(self.catalog.entries),
            "corpus_version": self.catalog.corpus_version,
            "embedding_model": self.embedder.model_name,
        }

    def clear_cache(self) -> int:
        return self.cache.clear()

    def _result(
        self,
        *,
        question: str,
        normalized: str,
        answer: CachedAnswer,
        cache_type: str,
        cache_key: str | None,
        cache_similarity: float | None,
        matched_question: str | None,
        started: float,
    ) -> AnswerResult:
        return AnswerResult(
            question=question,
            normalized_question=normalized,
            answer=answer,
            cache_type=cache_type,
            cache_key=cache_key,
            cache_similarity=cache_similarity,
            matched_question=matched_question,
            latency_ms=round((perf_counter() - started) * 1000, 3),
            metrics=self.metrics(),
        )

    def _cache_error(self, operation: str, error: Exception) -> None:
        self._increment("cache_errors")
        LOGGER.warning(
            "Semantic FAQ cache %s failed; continuing without cache (%s)",
            operation,
            type(error).__name__,
        )

    def _increment(self, *names: str) -> None:
        with self._lock:
            for name in names:
                self._metrics[name] += 1
