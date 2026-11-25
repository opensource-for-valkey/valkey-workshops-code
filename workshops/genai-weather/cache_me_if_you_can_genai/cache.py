"""Exact prompt and semantic vector caching with Valkey Search."""

from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
import logging
from typing import Any, Protocol
import numpy as np
from glide_sync import Batch, ExpirySet, ExpiryType, RequestError
from valkey_client_manager import scan_keys, search_document_keys
from .models import WeatherIntent

LOGGER = logging.getLogger(__name__)
CACHE_PREFIX = "genai-weather:v3"
ANSWER_PREFIX = f"{CACHE_PREFIX}:interpreted-answer"
PROMPT_PREFIX = f"{CACHE_PREFIX}:prompt"
EMBEDDING_PREFIX = f"{CACHE_PREFIX}:embedding"
INDEX_NAME = "genai_weather_interpreted_prompts_v3"


class Embedder(Protocol):
    @property
    def dimension(self) -> int: ...

    def embed(self, text: str) -> np.ndarray: ...


class SentenceTransformerEmbedder:
    """Lazily load a SentenceTransformer model."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        self.model_name = model_name
        self._model: Any | None = None

    def _load(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
        return self._model

    @property
    def dimension(self) -> int:
        return int(self._load().get_sentence_embedding_dimension())

    def embed(self, text: str) -> np.ndarray:
        vector = self._load().encode(text, convert_to_numpy=True)
        return np.asarray(vector, dtype=np.float32).reshape(-1)


@dataclass(frozen=True)
class CacheLookup:
    answer: dict[str, Any]
    cache_type: str
    matched_prompt: str | None = None
    similarity: float | None = None


@dataclass(frozen=True)
class SemanticProbe:
    embedding: np.ndarray
    lookup: CacheLookup | None


@dataclass(frozen=True)
class _SemanticCandidate:
    lookup: CacheLookup
    embedding: np.ndarray


class SemanticWeatherCache:
    """Store exact mappings, weather answers, and prompt vectors."""

    def __init__(
        self,
        client: Any,
        embedder: Embedder,
        *,
        ttl_seconds: int = 900,
        similarity_threshold: float = 0.9,
        search_candidates: int = 25,
        mmr_lambda: float = 0.85,
        mmr_top_n: int = 5,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be greater than zero")
        if not 0.0 <= similarity_threshold <= 1.0:
            raise ValueError("similarity_threshold must be between zero and one")
        if not 0.0 <= mmr_lambda <= 1.0:
            raise ValueError("mmr_lambda must be between zero and one")
        if mmr_top_n <= 0:
            raise ValueError("mmr_top_n must be greater than zero")
        self.client = client
        self.embedder = embedder
        self.ttl_seconds = ttl_seconds
        self.similarity_threshold = similarity_threshold
        self.search_candidates = search_candidates
        self.mmr_lambda = mmr_lambda
        self.mmr_top_n = mmr_top_n
        self._index_ready = False

    def get_exact(self, normalized_prompt: str) -> CacheLookup | None:
        pointer = self.client.get(self._prompt_key(normalized_prompt))
        if not pointer:
            return None
        answer = self._get_answer(self._decode(pointer))
        if answer is None:
            return None
        return CacheLookup(answer=answer, cache_type="exact")

    def find_semantic(
        self, normalized_prompt: str, intent: WeatherIntent
    ) -> SemanticProbe:
        embedding = self.embedder.embed(normalized_prompt)
        candidate_keys = self._candidate_keys(embedding)
        candidates: list[_SemanticCandidate] = []
        for key in candidate_keys:
            fields = self._decode_hash(self.client.hgetall(key))
            if not fields or any(
                (
                    fields.get(name) != value
                    for name, value in intent.constraints.items()
                )
            ):
                continue
            stored = fields.get("embedding")
            if not isinstance(stored, bytes):
                continue
            stored_embedding = np.frombuffer(stored, dtype=np.float32)
            similarity = self._cosine_similarity(embedding, stored_embedding)
            if similarity < self.similarity_threshold:
                continue
            answer_key = fields.get("answer_key")
            if not isinstance(answer_key, str):
                continue
            answer = self._get_answer(answer_key)
            if answer is None:
                continue
            candidates.append(
                _SemanticCandidate(
                    lookup=CacheLookup(
                        answer=answer,
                        cache_type="semantic",
                        matched_prompt=str(fields.get("original_prompt", "")),
                        similarity=similarity,
                    ),
                    embedding=stored_embedding,
                )
            )
        reranked = self._mmr_rerank(embedding, candidates)
        lookup = reranked[0].lookup if reranked else None
        return SemanticProbe(embedding=embedding, lookup=lookup)

    def _mmr_rerank(
        self, query_embedding: np.ndarray, candidates: list[_SemanticCandidate]
    ) -> list[_SemanticCandidate]:
        """Rerank qualified candidates using Maximal Marginal Relevance."""
        if not candidates:
            return []
        remaining = list(range(len(candidates)))
        first = max(
            remaining, key=lambda index: candidates[index].lookup.similarity or 0.0
        )
        selected = [first]
        remaining.remove(first)
        while remaining and len(selected) < min(self.mmr_top_n, len(candidates)):
            scored: list[tuple[float, float, int]] = []
            for index in remaining:
                relevance = candidates[index].lookup.similarity or 0.0
                redundancy = max(
                    (
                        self._cosine_similarity(
                            candidates[index].embedding,
                            candidates[selected_index].embedding,
                        )
                        for selected_index in selected
                    )
                )
                mmr_score = (
                    self.mmr_lambda * relevance - (1.0 - self.mmr_lambda) * redundancy
                )
                scored.append((mmr_score, relevance, index))
            next_index = max(scored)[2]
            selected.append(next_index)
            remaining.remove(next_index)
        return [candidates[index] for index in selected]

    def store(
        self,
        normalized_prompt: str,
        original_prompt: str,
        intent: WeatherIntent,
        answer: dict[str, Any],
        embedding: np.ndarray,
    ) -> None:
        answer_json = json.dumps(answer, separators=(",", ":"), sort_keys=True)
        answer_key = f"{ANSWER_PREFIX}:{self._digest(answer_json)}"
        prompt_key = self._prompt_key(normalized_prompt)
        embedding_key = f"{EMBEDDING_PREFIX}:{self._digest(normalized_prompt)}"
        mapping: dict[str, Any] = {
            "normalized_prompt": normalized_prompt,
            "original_prompt": original_prompt,
            "answer_key": answer_key,
            "embedding": np.asarray(embedding, dtype=np.float32).tobytes(),
            **intent.constraints,
        }
        pipeline = Batch(is_atomic=True)
        pipeline.set(
            answer_key, answer_json, expiry=ExpirySet(ExpiryType.SEC, self.ttl_seconds)
        )
        pipeline.set(
            prompt_key, answer_key, expiry=ExpirySet(ExpiryType.SEC, self.ttl_seconds)
        )
        pipeline.hset(embedding_key, field_value_map=mapping)
        pipeline.expire(embedding_key, self.ttl_seconds)
        self.client.exec(pipeline, raise_on_error=True)

    def link_exact(self, normalized_prompt: str, answer: dict[str, Any]) -> None:
        answer_json = json.dumps(answer, separators=(",", ":"), sort_keys=True)
        answer_key = f"{ANSWER_PREFIX}:{self._digest(answer_json)}"
        pipeline = Batch(is_atomic=True)
        pipeline.set(
            answer_key, answer_json, expiry=ExpirySet(ExpiryType.SEC, self.ttl_seconds)
        )
        pipeline.set(
            self._prompt_key(normalized_prompt),
            answer_key,
            expiry=ExpirySet(ExpiryType.SEC, self.ttl_seconds),
        )
        self.client.exec(pipeline, raise_on_error=True)

    def stats(self) -> dict[str, int]:
        return {
            "answers": self._count(f"{ANSWER_PREFIX}:*"),
            "exact_prompts": self._count(f"{PROMPT_PREFIX}:*"),
            "embeddings": self._count(f"{EMBEDDING_PREFIX}:*"),
        }

    def clear(self) -> int:
        cleared = 0
        batch: list[Any] = []
        for key in scan_keys(self.client, pattern=f"{CACHE_PREFIX}:*", count=100):
            batch.append(key)
            if len(batch) == 100:
                cleared += int(self.client.unlink(batch))
                batch.clear()
        if batch:
            cleared += int(self.client.unlink(batch))
        return cleared

    def _candidate_keys(self, embedding: np.ndarray) -> list[Any]:
        try:
            self._ensure_index()
            return search_document_keys(
                self.client,
                INDEX_NAME,
                np.asarray(embedding, dtype=np.float32).tobytes(),
                self.search_candidates,
            )
        except Exception as error:
            LOGGER.warning(
                "Valkey Search unavailable; using bounded scan fallback (%s)",
                type(error).__name__,
            )
            from itertools import islice

            return list(
                islice(
                    scan_keys(self.client, f"{EMBEDDING_PREFIX}:*", count=100),
                    self.search_candidates,
                )
            )

    def _ensure_index(self) -> None:
        if self._index_ready:
            return
        try:
            self.client.custom_command(["FT.INFO", INDEX_NAME])
        except RequestError as error:
            message = str(error).casefold()
            if "unknown index" not in message and "not found" not in message:
                raise
            self.client.custom_command(
                [
                    "FT.CREATE",
                    INDEX_NAME,
                    "ON",
                    "HASH",
                    "PREFIX",
                    "1",
                    f"{EMBEDDING_PREFIX}:",
                    "SCHEMA",
                    "location_id",
                    "TAG",
                    "start_at",
                    "TAG",
                    "end_at",
                    "TAG",
                    "granularity",
                    "TAG",
                    "units",
                    "TAG",
                    "normalized_prompt",
                    "TEXT",
                    "embedding",
                    "VECTOR",
                    "HNSW",
                    "6",
                    "TYPE",
                    "FLOAT32",
                    "DIM",
                    str(self.embedder.dimension),
                    "DISTANCE_METRIC",
                    "COSINE",
                ]
            )
        self._index_ready = True

    def _get_answer(self, answer_key: str) -> dict[str, Any] | None:
        raw = self.client.get(answer_key)
        if not raw:
            return None
        decoded = self._decode(raw)
        value = json.loads(decoded)
        return value if isinstance(value, dict) else None

    def _count(self, pattern: str) -> int:
        return sum((1 for _ in scan_keys(self.client, pattern=pattern, count=100)))

    @staticmethod
    def _prompt_key(normalized_prompt: str) -> str:
        return f"{PROMPT_PREFIX}:{SemanticWeatherCache._digest(normalized_prompt)}"

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _decode(value: Any) -> str:
        return value.decode("utf-8") if isinstance(value, bytes) else str(value)

    @staticmethod
    def _decode_hash(values: dict[Any, Any]) -> dict[str, Any]:
        decoded: dict[str, Any] = {}
        for raw_name, raw_value in values.items():
            name = SemanticWeatherCache._decode(raw_name)
            decoded[name] = (
                raw_value
                if name == "embedding"
                else SemanticWeatherCache._decode(raw_value)
            )
        return decoded

    @staticmethod
    def _cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
        if left.shape != right.shape:
            return 0.0
        denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
        if denominator == 0.0:
            return 0.0
        return float(np.dot(left, right) / denominator)
