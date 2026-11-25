"""HTTP client for OpenWeatherMap One Call API 4.0."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import requests

from openweathermap_api.cache import ResponseCache, build_cache_key


DEFAULT_BASE_URL = "https://api.openweathermap.org/data/4.0/onecall"
LOGGER = logging.getLogger(__name__)


class OpenWeatherMapError(Exception):
    """An error that can be returned safely by the local API."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 502,
        details: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details


class OpenWeatherMapClient:
    """Client for OpenWeatherMap One Call API 4.0 with optional caching."""

    def __init__(
        self,
        api_key: str | None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = 10.0,
        session: requests.Session | None = None,
        cache: ResponseCache | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()
        self.cache = cache

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    @property
    def cache_enabled(self) -> bool:
        return self.cache is not None

    def clear_cache(self) -> int:
        if self.cache is None:
            raise OpenWeatherMapError(
                "OpenWeatherMap cache is not configured",
                status_code=503,
            )
        try:
            return self.cache.clear()
        except Exception as error:
            raise OpenWeatherMapError(
                "Unable to clear the OpenWeatherMap cache",
                status_code=502,
            ) from error

    def current(self, params: dict[str, Any]) -> Any:
        return self._get("current", params)

    def timeline(self, interval: str, params: dict[str, Any]) -> Any:
        return self._get(f"timeline/{interval}", params)

    def alert(self, alert_id: str) -> Any:
        return self._get(f"alert/{quote(alert_id, safe='')}", {})

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        if not self.api_key:
            raise OpenWeatherMapError(
                "OpenWeatherMap API key is not configured",
                status_code=503,
            )
        request_params = {
            key: value
            for key, value in params.items()
            if value is not None and key.lower() != "appid"
        }
        cache_key: str | None = None
        if self.cache is not None:
            try:
                cache_key = build_cache_key(path, request_params)
                cached_payload = self.cache.get(cache_key)
                if cached_payload is not None:
                    return cached_payload
            except Exception as error:
                LOGGER.warning(
                    "OpenWeatherMap cache read failed; using upstream (%s)",
                    type(error).__name__,
                )
        request_params["appid"] = self.api_key
        try:
            response = self.session.get(
                f"{self.base_url}/{path}",
                params=request_params,
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as error:
            raise OpenWeatherMapError(
                "Unable to reach OpenWeatherMap",
                status_code=502,
            ) from error
        try:
            payload = response.json()
        except ValueError as error:
            raise OpenWeatherMapError(
                "OpenWeatherMap returned an invalid response",
                status_code=502,
                details={"upstream_status": response.status_code},
            ) from error
        if not response.ok:
            status_code = response.status_code if response.status_code < 500 else 502
            raise OpenWeatherMapError(
                "OpenWeatherMap request failed",
                status_code=status_code,
                details={
                    "upstream_status": response.status_code,
                    "upstream_error": payload,
                },
            )
        if self.cache is not None and cache_key is not None:
            try:
                self.cache.set(cache_key, payload)
            except Exception as error:
                LOGGER.warning(
                    "OpenWeatherMap cache write failed; returning upstream response (%s)",
                    type(error).__name__,
                )
        return payload
