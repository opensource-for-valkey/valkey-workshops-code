"""Flask API for natural-language OpenWeatherMap questions."""

from __future__ import annotations
import os
from typing import Any
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from valkey_client_manager import ValkeyClientManager
from timezonefinder import TimezoneFinder
from openweathermap_api.cache import ValkeyJsonCache
from openweathermap_api.client import OpenWeatherMapClient, OpenWeatherMapError
from openweathermap_api.geocoding import (
    GEOCODING_CACHE_KEY_PREFIX,
    OpenWeatherMapGeocodingClient,
)
from .cache import SemanticWeatherCache, SentenceTransformerEmbedder
from .locations import LocationResolver, UnknownLocationError
from .normalizer import PromptNormalizationError, PromptNormalizer
from .service import WeatherQuestionService
from .weather import OpenWeatherMapWeatherProvider

load_dotenv(os.environ.get("WORKSHOP_ENV_FILE", ".env"), override=False)


def _boolean(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def _api_key() -> str | None:
    return (
        os.getenv("OPENWEATHERMAP_API_KEY")
        or os.getenv("OPENWEATHER_API_KEY")
        or os.getenv("OWM_API_KEY")
    )


def _valkey_client(prefix: str, fallback_prefix: str) -> Any:
    manager = ValkeyClientManager(
        env_prefix=prefix, fallback_prefix=fallback_prefix, default_port=16379
    )
    return manager.client


def create_service_from_environment() -> WeatherQuestionService:
    response_cache = None
    if _boolean("OPENWEATHERMAP_CACHE_ENABLED", True):
        response_cache = ValkeyJsonCache(
            _valkey_client("OPENWEATHERMAP_CACHE", "VECTOR"),
            ttl_seconds=int(os.getenv("OPENWEATHERMAP_CACHE_TTL_SECONDS", "600")),
        )
    geocoding_cache = None
    if _boolean("OPENWEATHERMAP_GEOCODING_CACHE_ENABLED", True):
        geocoding_cache = ValkeyJsonCache(
            _valkey_client("OPENWEATHERMAP_GEOCODING_CACHE", "VECTOR"),
            ttl_seconds=int(
                os.getenv("OPENWEATHERMAP_GEOCODING_CACHE_TTL_SECONDS", "86400")
            ),
            key_prefix=GEOCODING_CACHE_KEY_PREFIX,
        )
    api_key = _api_key()
    timeout_seconds = float(os.getenv("OPENWEATHERMAP_TIMEOUT_SECONDS", "10"))
    geocoding_client = OpenWeatherMapGeocodingClient(
        api_key,
        base_url=os.getenv(
            "OPENWEATHERMAP_GEOCODING_BASE_URL",
            "https://api.openweathermap.org/geo/1.0/direct",
        ),
        timeout_seconds=timeout_seconds,
        cache=geocoding_cache,
    )
    location_resolver = LocationResolver(
        geocoder=geocoding_client, timezone_finder=TimezoneFinder(in_memory=True)
    )
    weather_client = OpenWeatherMapClient(
        api_key,
        base_url=os.getenv(
            "OPENWEATHERMAP_BASE_URL", "https://api.openweathermap.org/data/4.0/onecall"
        ),
        timeout_seconds=timeout_seconds,
        cache=response_cache,
    )
    weather_provider = OpenWeatherMapWeatherProvider(weather_client)
    semantic_cache = None
    if _boolean("GENAI_WEATHER_CACHE_ENABLED", True):
        cache_client = _valkey_client("GENAI_WEATHER_CACHE", "VECTOR")
        embedder = SentenceTransformerEmbedder(
            os.getenv(
                "GENAI_WEATHER_EMBEDDING_MODEL",
                os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
            )
        )
        semantic_cache = SemanticWeatherCache(
            cache_client,
            embedder,
            ttl_seconds=int(os.getenv("GENAI_WEATHER_CACHE_TTL_SECONDS", "900")),
            similarity_threshold=float(
                os.getenv("GENAI_WEATHER_SIMILARITY_THRESHOLD", "0.90")
            ),
            mmr_lambda=float(os.getenv("GENAI_WEATHER_MMR_LAMBDA", "0.85")),
            mmr_top_n=int(os.getenv("GENAI_WEATHER_MMR_TOP_N", "5")),
        )
    return WeatherQuestionService(
        PromptNormalizer(location_resolver), weather_provider, semantic_cache
    )


def create_app(
    service: WeatherQuestionService | None = None,
    *,
    allow_cache_clear: bool | None = None,
) -> Flask:
    app = Flask(__name__)
    app.json.ensure_ascii = False
    question_service = service or create_service_from_environment()
    if allow_cache_clear is None:
        allow_cache_clear = _boolean("GENAI_WEATHER_CACHE_ALLOW_CLEAR", False)

    @app.errorhandler(PromptNormalizationError)
    @app.errorhandler(UnknownLocationError)
    def handle_prompt_error(error: ValueError) -> tuple[Any, int]:
        return (jsonify({"error": str(error)}), 400)

    @app.errorhandler(OpenWeatherMapError)
    def handle_weather_error(error: OpenWeatherMapError) -> tuple[Any, int]:
        return (jsonify({"error": error.message}), error.status_code)

    @app.get("/")
    def index() -> Any:
        return jsonify(
            {
                "service": "Cache Me If You Can: GenAI Weather",
                "endpoint": "POST /weather returns a compact JSON bot-reply envelope",
                "example": {
                    "prompt": "What's the weather today in Buenos Aires?",
                    "units": "metric",
                },
                "cache_layers": [
                    "OpenWeatherMap response cache (Valkey JSON)",
                    "Interpreted answer cache (exact + semantic)",
                ],
            }
        )

    @app.get("/health")
    def health() -> Any:
        return jsonify(
            {
                "status": "ok",
                "openweathermap_configured": question_service.weather_provider.is_configured,
                "openweathermap_response_cache_enabled": question_service.weather_provider.response_cache_enabled,
                "interpreted_answer_cache_enabled": question_service.semantic_cache
                is not None,
                "cache_clear_allowed": allow_cache_clear,
            }
        )

    @app.post("/weather")
    def weather() -> Any:
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return (jsonify({"error": "Request body must be a JSON object."}), 400)
        prompt = body.get("prompt")
        if not isinstance(prompt, str):
            return (jsonify({"error": "Prompt must be a string."}), 400)
        units = body.get("units", "metric")
        if not isinstance(units, str):
            return (jsonify({"error": "Units must be a string."}), 400)
        result = question_service.ask(prompt, units=units.casefold())
        response = jsonify(
            {
                "bot-reply": result["prose"],
                "latency_ms": result["latency_ms"],
                "cache": result["cache"],
                "metrics": result["metrics"],
            }
        )
        response.headers["X-GenAI-Cache-Hit"] = str(result["cache"]["hit"]).lower()
        response.headers["X-GenAI-Cache-Type"] = result["cache"]["type"]
        response.headers["X-Total-Time-Ms"] = f"{result['latency_ms']:.3f}"
        response.headers["Server-Timing"] = f"total;dur={result['latency_ms']:.3f}"
        if result["cache"]["similarity"] is not None:
            response.headers["X-Semantic-Similarity"] = str(
                result["cache"]["similarity"]
            )
        return response

    @app.get("/metrics")
    def metrics() -> Any:
        return jsonify(question_service.metrics())

    @app.delete("/cache")
    def clear_cache() -> tuple[Any, int] | Any:
        if not allow_cache_clear:
            return (
                jsonify({"error": "Interpreted answer cache clearing is disabled"}),
                403,
            )
        try:
            cleared = question_service.clear_cache()
        except RuntimeError as error:
            return (jsonify({"error": str(error)}), 503)
        return jsonify({"status": "ok", "cleared_interpreted_items": cleared})

    return app


def main() -> None:
    from rich.console import Console
    from rich.logging import RichHandler
    import logging

    logging.basicConfig(
        level=logging.INFO, handlers=[RichHandler(rich_tracebacks=True)]
    )
    Console().print("[bold]Valkey GLIDE weather workshop[/bold]")
    app = create_app()
    app.run(
        host=os.getenv("GENAI_WEATHER_API_HOST", "127.0.0.1"),
        port=int(os.getenv("GENAI_WEATHER_API_PORT", "5001")),
        debug=_boolean("FLASK_DEBUG", False),
    )


if __name__ == "__main__":
    main()
