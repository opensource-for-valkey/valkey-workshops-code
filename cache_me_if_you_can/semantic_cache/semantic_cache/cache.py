from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

import numpy as np
import valkey

from .models import CacheLookup, CacheProbe, CachedAnswer, Embedder


LOGGER = logging.getLogger(__name__)
CACHE_PREFIX = "semantic-faq-cache:v1"
ANSWER_PREFIX = f"{CACHE_PREFIX}:answer"
PROMPT_PREFIX = f"{CACHE_PREFIX}:prompt"
EMBEDDING_PREFIX = f"{CACHE_PREFIX}:embedding"
INDEX_NAME = "semantic_faq_cache_v1"


class ValkeySemanticCache:
    """Exact pointers plus semantic vector reuse stored in Valkey."""

    def __init__(
        self,
        client: Any,
        embedder: Embedder,
        *,
        ttl_seconds: int = 3600,
        similarity_threshold: float = 0.88,
        search_candidates: int = 10,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be greater than zero")
        if not 0.0 <= similarity_threshold <= 1.0:
            raise ValueError("similarity_threshold must be between zero and one")
        if search_candidates <= 0:
            raise ValueError("search_candidates must be greater than zero")
        self.client = client
        self.embedder = embedder
        self.ttl_seconds = ttl_seconds
        self.similarity_threshold = similarity_threshold
        self.search_candidates = search_candidates
        self._index_ready = False

    def lookup(
        self,
        normalized_question: str,
        corpus_version: str,
        scope: str,
    ) -> CacheProbe:
        exact_key = self._prompt_key(normalized_question)
        pointer = self.client.get(exact_key)
        if pointer:
            answer = self._get_answer(self._decode(pointer))
            if answer is not None and answer.corpus_version == corpus_version:
                return CacheProbe(
                    embedding=None,
                    lookup=CacheLookup(
                        answer=answer,
                        cache_type="exact",
                        cache_key=exact_key,
                    ),
                )

        embedding = self.embedder.embed(normalized_question)
        candidates: list[CacheLookup] = []
        for raw_key in self._candidate_keys(embedding):
            key = self._decode(raw_key)
            fields = self._decode_hash(self.client.hgetall(raw_key))
            if fields.get("corpus_version") != corpus_version:
                continue
            if fields.get("scope") != scope:
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
            if answer is None or answer.corpus_version != corpus_version:
                continue
            candidates.append(
                CacheLookup(
                    answer=answer,
                    cache_type="semantic",
                    matched_question=str(fields.get("original_question", "")),
                    similarity=similarity,
                    cache_key=key,
                )
            )

        lookup = (
            max(candidates, key=lambda candidate: candidate.similarity or 0.0)
            if candidates
            else None
        )
        return CacheProbe(embedding=embedding, lookup=lookup)

    def store(
        self,
        normalized_question: str,
        original_question: str,
        answer: CachedAnswer,
        embedding: np.ndarray,
        scope: str,
    ) -> str:
        answer_json = json.dumps(
            answer.to_dict(),
            separators=(",", ":"),
            sort_keys=True,
        )
        answer_key = f"{ANSWER_PREFIX}:{self._digest(answer_json)}"
        prompt_key = self._prompt_key(normalized_question)
        embedding_key = f"{EMBEDDING_PREFIX}:{self._digest(normalized_question)}"

        pipeline = self.client.pipeline(transaction=True)
        pipeline.setex(answer_key, self.ttl_seconds, answer_json)
        pipeline.setex(prompt_key, self.ttl_seconds, answer_key)
        pipeline.hset(
            embedding_key,
            mapping={
                "normalized_question": normalized_question,
                "original_question": original_question,
                "answer_key": answer_key,
                "corpus_version": answer.corpus_version,
                "scope": scope,
                "embedding": np.asarray(embedding, dtype=np.float32).tobytes(),
            },
        )
        pipeline.expire(embedding_key, self.ttl_seconds)
        pipeline.execute()
        return embedding_key

    def link_exact(
        self,
        normalized_question: str,
        answer: CachedAnswer,
    ) -> str:
        answer_json = json.dumps(
            answer.to_dict(),
            separators=(",", ":"),
            sort_keys=True,
        )
        answer_key = f"{ANSWER_PREFIX}:{self._digest(answer_json)}"
        prompt_key = self._prompt_key(normalized_question)
        pipeline = self.client.pipeline(transaction=True)
        pipeline.setex(answer_key, self.ttl_seconds, answer_json)
        pipeline.setex(prompt_key, self.ttl_seconds, answer_key)
        pipeline.execute()
        return prompt_key

    def stats(self) -> dict[str, int]:
        return {
            "answers": self._count(f"{ANSWER_PREFIX}:*"),
            "exact_questions": self._count(f"{PROMPT_PREFIX}:*"),
            "embeddings": self._count(f"{EMBEDDING_PREFIX}:*"),
        }

    def clear(self) -> int:
        cleared = 0
        batch: list[Any] = []
        for key in self.client.scan_iter(match=f"{CACHE_PREFIX}:*", count=100):
            batch.append(key)
            if len(batch) == 100:
                cleared += int(self.client.unlink(*batch))
                batch.clear()
        if batch:
            cleared += int(self.client.unlink(*batch))
        return cleared

    def ping(self) -> bool:
        return bool(self.client.ping())

    def _candidate_keys(self, embedding: np.ndarray) -> list[Any]:
        try:
            self._ensure_index()
            from valkey.commands.search.query import Query

            query = (
                Query(
                    f"*=>[KNN {self.search_candidates} "
                    "@embedding $vector AS vector_distance]"
                )
                .return_fields("vector_distance")
                .dialect(2)
            )
            results = self.client.ft(INDEX_NAME).search(
                query,
                {"vector": np.asarray(embedding, dtype=np.float32).tobytes()},
            )
            return [document.id for document in results.docs]
        except Exception as error:
            LOGGER.warning(
                "Valkey Search unavailable; using bounded scan fallback (%s)",
                type(error).__name__,
            )
            return list(
                self.client.scan_iter(
                    match=f"{EMBEDDING_PREFIX}:*",
                    count=100,
                )
            )[: self.search_candidates]

    def _ensure_index(self) -> None:
        if self._index_ready:
            return
        try:
            self.client.execute_command("FT.INFO", INDEX_NAME)
        except valkey.ResponseError as error:
            message = str(error).casefold()
            if "unknown index" not in message and "not found" not in message:
                raise
            self.client.execute_command(
                "FT.CREATE",
                INDEX_NAME,
                "ON",
                "HASH",
                "PREFIX",
                "1",
                f"{EMBEDDING_PREFIX}:",
                "SCHEMA",
                "corpus_version",
                "TAG",
                "scope",
                "TAG",
                "normalized_question",
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
            )
        self._index_ready = True

    def _get_answer(self, answer_key: str) -> CachedAnswer | None:
        raw = self.client.get(answer_key)
        if not raw:
            return None
        value = json.loads(self._decode(raw))
        if not isinstance(value, dict):
            return None
        return CachedAnswer.from_dict(value)

    def _count(self, pattern: str) -> int:
        return sum(1 for _ in self.client.scan_iter(match=pattern, count=100))

    @staticmethod
    def _prompt_key(normalized_question: str) -> str:
        return f"{PROMPT_PREFIX}:{ValkeySemanticCache._digest(normalized_question)}"

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
            name = ValkeySemanticCache._decode(raw_name)
            decoded[name] = (
                raw_value
                if name == "embedding"
                else ValkeySemanticCache._decode(raw_value)
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
