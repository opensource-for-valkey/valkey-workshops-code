from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


DEMO_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = DEMO_DIR.parent / "data"


def _path_from_environment(name: str, default: Path) -> Path:
    path = Path(os.getenv(name, str(default))).expanduser()
    return path if path.is_absolute() else DEMO_DIR / path


def _boolean(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().casefold() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    valkey_url: str
    cache_ttl_seconds: int
    cache_similarity_threshold: float
    faq_similarity_threshold: float
    search_candidates: int
    embedding_model: str
    allow_cache_clear: bool

    @classmethod
    def from_environment(cls) -> Settings:
        load_dotenv(DEMO_DIR / ".env")
        settings = cls(
            data_dir=_path_from_environment(
                "SEMANTIC_FAQ_DATA_DIR",
                DEFAULT_DATA_DIR,
            ),
            valkey_url=os.getenv(
                "SEMANTIC_FAQ_VALKEY_URL",
                "valkey://localhost:16379/0",
            ),
            cache_ttl_seconds=int(
                os.getenv("SEMANTIC_FAQ_CACHE_TTL_SECONDS", "3600")
            ),
            cache_similarity_threshold=float(
                os.getenv("SEMANTIC_FAQ_CACHE_SIMILARITY_THRESHOLD", "0.88")
            ),
            faq_similarity_threshold=float(
                os.getenv("SEMANTIC_FAQ_RETRIEVAL_THRESHOLD", "0.45")
            ),
            search_candidates=int(
                os.getenv("SEMANTIC_FAQ_SEARCH_CANDIDATES", "10")
            ),
            embedding_model=os.getenv(
                "SEMANTIC_FAQ_EMBEDDING_MODEL",
                "all-MiniLM-L6-v2",
            ),
            allow_cache_clear=_boolean(
                "SEMANTIC_FAQ_CACHE_ALLOW_CLEAR",
                False,
            ),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if not self.data_dir.is_dir():
            raise ValueError(f"FAQ data directory does not exist: {self.data_dir}")
        if self.cache_ttl_seconds <= 0:
            raise ValueError("SEMANTIC_FAQ_CACHE_TTL_SECONDS must be positive")
        if not 0.0 <= self.cache_similarity_threshold <= 1.0:
            raise ValueError(
                "SEMANTIC_FAQ_CACHE_SIMILARITY_THRESHOLD must be between 0 and 1"
            )
        if not 0.0 <= self.faq_similarity_threshold <= 1.0:
            raise ValueError(
                "SEMANTIC_FAQ_RETRIEVAL_THRESHOLD must be between 0 and 1"
            )
        if self.search_candidates <= 0:
            raise ValueError("SEMANTIC_FAQ_SEARCH_CANDIDATES must be positive")
