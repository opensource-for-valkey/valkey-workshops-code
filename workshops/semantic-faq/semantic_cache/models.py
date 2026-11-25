from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol


class Embedder(Protocol):
    model_name: str

    @property
    def dimension(self) -> int: ...

    def embed(self, text: str) -> Any: ...

    def embed_many(self, texts: list[str]) -> Any: ...


@dataclass(frozen=True)
class FaqEntry:
    question: str
    answer: str
    provider: str
    source_file: str
    section: str


@dataclass(frozen=True)
class FaqMatch:
    entry: FaqEntry
    similarity: float


@dataclass(frozen=True)
class CatalogSearch:
    match: FaqMatch | None
    suggestions: tuple[FaqMatch, ...]


@dataclass(frozen=True)
class CachedAnswer:
    answer: str
    source_question: str
    provider: str
    source_file: str
    section: str
    retrieval_similarity: float
    corpus_version: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> CachedAnswer:
        return cls(
            answer=str(value["answer"]),
            source_question=str(value["source_question"]),
            provider=str(value["provider"]),
            source_file=str(value["source_file"]),
            section=str(value["section"]),
            retrieval_similarity=float(value["retrieval_similarity"]),
            corpus_version=str(value["corpus_version"]),
        )


@dataclass(frozen=True)
class CacheLookup:
    answer: CachedAnswer
    cache_type: str
    matched_question: str | None = None
    similarity: float | None = None
    cache_key: str | None = None


@dataclass(frozen=True)
class CacheProbe:
    embedding: Any | None
    lookup: CacheLookup | None


@dataclass(frozen=True)
class AnswerResult:
    question: str
    normalized_question: str
    answer: CachedAnswer
    cache_type: str
    cache_key: str | None
    cache_similarity: float | None
    matched_question: str | None
    latency_ms: float
    metrics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "answer": self.answer.answer,
            "source": {
                "provider": self.answer.provider,
                "file": self.answer.source_file,
                "section": self.answer.section,
                "faq_question": self.answer.source_question,
            },
            "retrieval": {
                "similarity": round(self.answer.retrieval_similarity, 4),
            },
            "cache": {
                "hit": self.cache_type in {"exact", "semantic"},
                "type": self.cache_type,
                "key": self.cache_key,
                "similarity": (
                    round(self.cache_similarity, 4)
                    if self.cache_similarity is not None
                    else None
                ),
                "matched_question": self.matched_question,
            },
            "latency_ms": self.latency_ms,
            "metrics": self.metrics,
        }
