from __future__ import annotations

from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
import valkey

from .cache import ValkeySemanticCache
from .catalog import FaqCatalog
from .embeddings import SentenceTransformerEmbedder
from .service import FaqAnswerService, QuestionNotFoundError
from .settings import Settings


class QuestionRequest(BaseModel):
    question: Annotated[str, Field(min_length=3, max_length=500)]

    @field_validator("question")
    @classmethod
    def reject_blank_question(cls, question: str) -> str:
        normalized = " ".join(question.split())
        if len(normalized) < 3:
            raise ValueError("question must contain at least 3 non-space characters")
        return normalized


def create_service_from_environment() -> tuple[FaqAnswerService, Settings]:
    settings = Settings.from_environment()
    embedder = SentenceTransformerEmbedder(settings.embedding_model)
    catalog = FaqCatalog.from_directory(
        settings.data_dir,
        embedder=embedder,
        similarity_threshold=settings.faq_similarity_threshold,
    )
    client = valkey.from_url(
        settings.valkey_url,
        decode_responses=False,
        socket_connect_timeout=5,
        socket_timeout=5,
        health_check_interval=30,
    )
    cache = ValkeySemanticCache(
        client,
        embedder,
        ttl_seconds=settings.cache_ttl_seconds,
        similarity_threshold=settings.cache_similarity_threshold,
        search_candidates=settings.search_candidates,
    )
    return (
        FaqAnswerService(
            catalog=catalog,
            cache=cache,
            embedder=embedder,
        ),
        settings,
    )


def create_app(
    service: FaqAnswerService | None = None,
    *,
    allow_cache_clear: bool | None = None,
) -> FastAPI:
    settings: Settings | None = None
    if service is None:
        service, settings = create_service_from_environment()
    if allow_cache_clear is None:
        allow_cache_clear = (
            settings.allow_cache_clear if settings is not None else False
        )

    app = FastAPI(
        title="Valkey Managed Services FAQ Semantic Cache",
        version="1.0.0",
        description=(
            "Answers managed Valkey service FAQs and reuses prior answers by "
            "semantic similarity."
        ),
    )

    @app.exception_handler(QuestionNotFoundError)
    def handle_question_not_found(
        _request: Any,
        error: QuestionNotFoundError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={
                "detail": {
                    "message": str(error),
                    "suggestions": error.suggestions,
                }
            },
        )

    @app.get("/")
    def index() -> dict[str, Any]:
        return {
            "service": app.title,
            "ask": {
                "method": "POST",
                "path": "/ask",
                "body": {"question": "What deployment options does ElastiCache have?"},
            },
            "docs": "/docs",
        }

    @app.get("/health")
    def health() -> dict[str, Any]:
        return service.health()

    @app.get("/metrics")
    def metrics() -> dict[str, Any]:
        return service.metrics()

    @app.post("/ask")
    def ask(payload: QuestionRequest, response: Response) -> dict[str, Any]:
        result = service.answer(payload.question)
        response.headers["X-Semantic-Cache-Hit"] = str(
            result.cache_type in {"exact", "semantic"}
        ).lower()
        response.headers["X-Semantic-Cache-Type"] = result.cache_type
        response.headers["X-Total-Time-Ms"] = f"{result.latency_ms:.3f}"
        if result.cache_similarity is not None:
            response.headers["X-Semantic-Similarity"] = (
                f"{result.cache_similarity:.4f}"
            )
        return result.to_dict()

    @app.delete("/cache")
    def clear_cache() -> dict[str, Any]:
        if not allow_cache_clear:
            raise HTTPException(
                status_code=403,
                detail="Semantic cache clearing is disabled.",
            )
        return {
            "status": "ok",
            "cleared_items": service.clear_cache(),
        }

    return app


app = create_app()
