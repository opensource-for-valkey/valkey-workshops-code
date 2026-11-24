"""Flask API proxy for OpenWeatherMap One Call API 4.0."""

from __future__ import annotations
import logging
import math
import os
import time
from pathlib import Path
from typing import Any
from dotenv import load_dotenv
from flask import Flask, g, jsonify, request
from valkey_client_manager import ValkeyClientManager
from openweathermap_api.cache import ValkeyJsonCache
from openweathermap_api.client import (
    DEFAULT_BASE_URL,
    OpenWeatherMapClient,
    OpenWeatherMapError,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(os.environ.get("WORKSHOP_ENV_FILE", ".env"), override=False)
LOGGER = logging.getLogger(__name__)
TIMELINE_INTERVALS = frozenset({"1min", "15min", "1h", "1day"})
VALID_UNITS = frozenset({"standard", "metric", "imperial"})


def _api_key_from_environment() -> str | None:
    return (
        os.getenv("OPENWEATHERMAP_API_KEY")
        or os.getenv("OPENWEATHER_API_KEY")
        or os.getenv("OWM_API_KEY")
    )


def _timeout_from_environment() -> float:
    raw_timeout = os.getenv("OPENWEATHERMAP_TIMEOUT_SECONDS", "10")
    try:
        timeout = float(raw_timeout)
    except ValueError as error:
        raise RuntimeError("OPENWEATHERMAP_TIMEOUT_SECONDS must be a number") from error
    if timeout <= 0:
        raise RuntimeError("OPENWEATHERMAP_TIMEOUT_SECONDS must be greater than zero")
    return timeout


def _boolean_from_environment(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be true or false")


def _integer_from_environment(name: str, default: str, minimum: int = 1) -> int:
    raw_value = os.getenv(name, default)
    try:
        value = int(raw_value)
    except ValueError as error:
        raise RuntimeError(f"{name} must be an integer") from error
    if value < minimum:
        raise RuntimeError(f"{name} must be at least {minimum}")
    return value


def _cache_from_environment() -> ValkeyJsonCache | None:
    if not _boolean_from_environment("OPENWEATHERMAP_CACHE_ENABLED", True):
        return None
    ttl_seconds = _integer_from_environment("OPENWEATHERMAP_CACHE_TTL_SECONDS", "600")
    host = (
        os.getenv("OPENWEATHERMAP_CACHE_HOST")
        or os.getenv("VECTOR_HOST")
        or os.getenv("CACHE_HOST", "localhost")
    )
    port = _integer_from_environment(
        "OPENWEATHERMAP_CACHE_PORT", os.getenv("VECTOR_PORT", "16379")
    )
    database = _integer_from_environment(
        "OPENWEATHERMAP_CACHE_DB", os.getenv("CACHE_DB", "0"), minimum=0
    )
    try:
        manager = ValkeyClientManager(
            env_prefix="OPENWEATHERMAP_CACHE",
            fallback_prefix="VECTOR",
            default_port=16379,
        )
        return ValkeyJsonCache(manager.client, ttl_seconds=ttl_seconds)
    except Exception as error:
        LOGGER.warning(
            "OpenWeatherMap cache initialization failed; caching disabled (%s)",
            type(error).__name__,
        )
        return None


def _request_params() -> dict[str, Any]:
    params: dict[str, Any] = request.args.to_dict(flat=True)
    params.pop("appid", None)
    return params


def _validated_location_params() -> dict[str, Any]:
    params = _request_params()
    missing = [name for name in ("lat", "lon") if not params.get(name)]
    if missing:
        raise OpenWeatherMapError(
            f"Missing required query parameter(s): {', '.join(missing)}",
            status_code=400,
        )
    try:
        latitude = float(params["lat"])
        longitude = float(params["lon"])
    except (TypeError, ValueError) as error:
        raise OpenWeatherMapError(
            "lat and lon must be numbers", status_code=400
        ) from error
    if not math.isfinite(latitude) or not -90 <= latitude <= 90:
        raise OpenWeatherMapError("lat must be between -90 and 90", status_code=400)
    if not math.isfinite(longitude) or not -180 <= longitude <= 180:
        raise OpenWeatherMapError("lon must be between -180 and 180", status_code=400)
    units = params.get("units")
    if units:
        units = units.lower()
        if units not in VALID_UNITS:
            raise OpenWeatherMapError(
                "units must be one of: standard, metric, imperial", status_code=400
            )
        params["units"] = units
    params["lat"] = latitude
    params["lon"] = longitude
    return params


def create_app(
    client: OpenWeatherMapClient | None = None, *, allow_cache_clear: bool | None = None
) -> Flask:
    """Create the Flask application, optionally with injected dependencies."""
    app = Flask(__name__)
    weather_client = client or OpenWeatherMapClient(
        _api_key_from_environment(),
        base_url=os.getenv("OPENWEATHERMAP_BASE_URL", DEFAULT_BASE_URL),
        timeout_seconds=_timeout_from_environment(),
        cache=_cache_from_environment(),
    )
    cache_clear_allowed = (
        _boolean_from_environment("OPENWEATHERMAP_CACHE_ALLOW_CLEAR", False)
        if allow_cache_clear is None
        else allow_cache_clear
    )
    app.extensions["openweathermap_client"] = weather_client
    app.extensions["openweathermap_cache"] = weather_client.cache
    app.extensions["openweathermap_cache_clear_allowed"] = cache_clear_allowed

    @app.before_request
    def start_request_timer() -> None:
        g.request_started_at = time.perf_counter()

    @app.after_request
    def add_request_timing(response):
        started_at = getattr(g, "request_started_at", time.perf_counter())
        total_time_ms = round((time.perf_counter() - started_at) * 1000, 3)
        response.headers["X-Total-Time-Ms"] = f"{total_time_ms:.3f}"
        response.headers["Server-Timing"] = f"total;dur={total_time_ms:.3f}"
        if response.is_json:
            payload = response.get_json(silent=True)
            if isinstance(payload, dict):
                payload["total_time_ms"] = total_time_ms
                response.set_data(app.json.dumps(payload))
                response.mimetype = "application/json"
        return response

    @app.errorhandler(OpenWeatherMapError)
    def handle_openweathermap_error(error: OpenWeatherMapError):
        body: dict[str, Any] = {"error": error.message}
        if error.details is not None:
            body["details"] = error.details
        return (jsonify(body), error.status_code)

    @app.get("/")
    def index():
        return jsonify(
            {
                "name": "OpenWeatherMap One Call API 4.0 proxy",
                "endpoints": [
                    "/health",
                    "DELETE /cache",
                    "/current?lat={latitude}&lon={longitude}",
                    "/timeline/{1min|15min|1h|1day}?lat={latitude}&lon={longitude}",
                    "/alert/{alert_id}",
                ],
            }
        )

    @app.get("/health")
    def health():
        return jsonify(
            {
                "status": "ok",
                "openweathermap_configured": weather_client.is_configured,
                "openweathermap_cache_enabled": weather_client.cache_enabled,
                "openweathermap_cache_clear_allowed": cache_clear_allowed,
            }
        )

    @app.delete("/cache")
    def clear_weather_cache():
        if not cache_clear_allowed:
            raise OpenWeatherMapError(
                "OpenWeatherMap cache clearing is disabled", status_code=403
            )
        cleared_items = weather_client.clear_cache()
        return jsonify({"status": "ok", "cleared_items": cleared_items})

    @app.get("/current")
    def current_weather():
        return jsonify(weather_client.current(_validated_location_params()))

    @app.get("/timeline/<interval>")
    def weather_timeline(interval: str):
        if interval not in TIMELINE_INTERVALS:
            raise OpenWeatherMapError(
                "interval must be one of: 1min, 15min, 1h, 1day", status_code=400
            )
        return jsonify(weather_client.timeline(interval, _validated_location_params()))

    @app.get("/alert/<alert_id>")
    def weather_alert(alert_id: str):
        return jsonify(weather_client.alert(alert_id))

    return app


app = create_app()


def main() -> None:
    from rich.console import Console
    from rich.logging import RichHandler
    import logging

    logging.basicConfig(
        level=logging.INFO, handlers=[RichHandler(rich_tracebacks=True)]
    )
    Console().print("[bold]Valkey GLIDE weather workshop[/bold]")
    host = os.getenv("OPENWEATHERMAP_API_HOST", "127.0.0.1")
    port = int(os.getenv("OPENWEATHERMAP_API_PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "false").lower() in {"1", "true", "yes"}
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()
