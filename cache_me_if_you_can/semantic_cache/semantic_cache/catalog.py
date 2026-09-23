from __future__ import annotations

import hashlib
from pathlib import Path
import re
from threading import Lock

import numpy as np

from .models import CatalogSearch, Embedder, FaqEntry, FaqMatch


PROVIDERS = {
    "aws-elasticache-faq.md": "Amazon ElastiCache",
    "gcp-memorystore-valkey-faq.md": "Google Cloud Memorystore",
    "heroku-key-value-store-faq.md": "Heroku Key-Value Store",
    "momento-cache-faq.md": "Momento Cache",
    "oci-cache-faq.md": "OCI Cache",
}

HEADING = re.compile(r"^(?P<level>#{1,6})\s+(?P<text>.+?)\s*$")
BOLD_QUESTION = re.compile(r"^\*\*(?P<text>.+\?)\*\*\s*$")


def _clean_answer(lines: list[str]) -> str:
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and (
        not lines[-1].strip()
        or lines[-1].startswith("*Source:")
        or lines[-1].startswith("*Content licensed")
        or lines[-1].strip() == "---"
    ):
        lines.pop()
    return "\n".join(lines).strip()


def parse_faq_file(path: Path) -> list[FaqEntry]:
    provider = PROVIDERS.get(path.name, path.stem)
    entries: list[FaqEntry] = []
    section = "General"
    question: str | None = None
    answer_lines: list[str] = []

    def flush() -> None:
        nonlocal question, answer_lines
        if question is not None:
            answer = _clean_answer(answer_lines)
            if answer:
                entries.append(
                    FaqEntry(
                        question=question,
                        answer=answer,
                        provider=provider,
                        source_file=path.name,
                        section=section,
                    )
                )
        question = None
        answer_lines = []

    for line in path.read_text(encoding="utf-8").splitlines():
        heading = HEADING.match(line)
        bold_question = BOLD_QUESTION.match(line)
        if heading:
            text = heading.group("text").strip()
            if text.endswith("?"):
                flush()
                question = text
            else:
                flush()
                if len(heading.group("level")) >= 2:
                    section = text
            continue
        if bold_question:
            flush()
            question = bold_question.group("text").strip()
            continue
        if question is not None:
            answer_lines.append(line)

    flush()
    return entries


def load_faq_directory(data_dir: Path) -> tuple[list[FaqEntry], str]:
    paths = sorted(data_dir.glob("*-faq.md"))
    if not paths:
        raise FileNotFoundError(f"No FAQ Markdown files found in {data_dir}")

    digest = hashlib.sha256()
    entries: list[FaqEntry] = []
    for path in paths:
        content = path.read_bytes()
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content)
        entries.extend(parse_faq_file(path))

    if not entries:
        raise ValueError(f"No FAQ entries could be parsed from {data_dir}")
    return entries, digest.hexdigest()


class FaqCatalog:
    """Retrieve the most relevant managed-service FAQ behind one interface."""

    def __init__(
        self,
        *,
        entries: list[FaqEntry],
        corpus_version: str,
        embedder: Embedder,
        similarity_threshold: float = 0.45,
        suggestion_count: int = 3,
    ) -> None:
        if not entries:
            raise ValueError("entries must not be empty")
        if not 0.0 <= similarity_threshold <= 1.0:
            raise ValueError("similarity_threshold must be between zero and one")
        if suggestion_count <= 0:
            raise ValueError("suggestion_count must be greater than zero")
        self.entries = tuple(entries)
        self.corpus_version = corpus_version
        self.embedder = embedder
        self.similarity_threshold = similarity_threshold
        self.suggestion_count = suggestion_count
        self._embeddings: np.ndarray | None = None
        self._lock = Lock()

    @classmethod
    def from_directory(
        cls,
        data_dir: Path,
        *,
        embedder: Embedder,
        similarity_threshold: float = 0.45,
        suggestion_count: int = 3,
    ) -> FaqCatalog:
        entries, corpus_version = load_faq_directory(data_dir)
        return cls(
            entries=entries,
            corpus_version=corpus_version,
            embedder=embedder,
            similarity_threshold=similarity_threshold,
            suggestion_count=suggestion_count,
        )

    def search(
        self,
        question: str,
        *,
        embedding: np.ndarray | None = None,
        source_file: str | None = None,
    ) -> CatalogSearch:
        matrix = self._embedding_matrix()
        query = self._normalize(
            embedding if embedding is not None else self.embedder.embed(question)
        )
        similarities = matrix @ query
        candidate_indexes = np.array(
            [
                index
                for index, entry in enumerate(self.entries)
                if source_file is None or entry.source_file == source_file
            ],
            dtype=np.int64,
        )
        if candidate_indexes.size == 0:
            return CatalogSearch(match=None, suggestions=())
        ranked = candidate_indexes[
            np.argsort(similarities[candidate_indexes])[::-1]
        ]
        suggestions = tuple(
            FaqMatch(
                entry=self.entries[int(index)],
                similarity=float(similarities[int(index)]),
            )
            for index in ranked[: self.suggestion_count]
        )
        best = suggestions[0]
        return CatalogSearch(
            match=best if best.similarity >= self.similarity_threshold else None,
            suggestions=suggestions,
        )

    def _embedding_matrix(self) -> np.ndarray:
        if self._embeddings is None:
            with self._lock:
                if self._embeddings is None:
                    vectors = self.embedder.embed_many(
                        [entry.question for entry in self.entries]
                    )
                    self._embeddings = np.vstack(
                        [self._normalize(vector) for vector in vectors]
                    )
        return self._embeddings

    @staticmethod
    def _normalize(vector: np.ndarray) -> np.ndarray:
        value = np.asarray(vector, dtype=np.float32).reshape(-1)
        norm = float(np.linalg.norm(value))
        if norm == 0.0:
            raise ValueError("embedding must not be a zero vector")
        return value / norm
