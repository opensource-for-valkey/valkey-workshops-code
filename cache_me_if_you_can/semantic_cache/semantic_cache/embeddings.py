from __future__ import annotations

from threading import Lock
from typing import Any

import numpy as np


class SentenceTransformerEmbedder:
    """Lazily create normalized FLOAT32 sentence embeddings."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        self.model_name = model_name
        self._model: Any | None = None
        self._lock = Lock()

    def _load(self) -> Any:
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from sentence_transformers import SentenceTransformer

                    self._model = SentenceTransformer(self.model_name)
        return self._model

    @property
    def dimension(self) -> int:
        return int(self._load().get_sentence_embedding_dimension())

    def embed(self, text: str) -> np.ndarray:
        vector = self._load().encode(
            text,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return np.asarray(vector, dtype=np.float32).reshape(-1)

    def embed_many(self, texts: list[str]) -> np.ndarray:
        vectors = self._load().encode(
            texts,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return np.asarray(vectors, dtype=np.float32)
