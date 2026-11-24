"""OpenWeatherMap Direct Geocoding client with cache-aside support."""

from __future__ import annotations

import logging
from typing import Any

import requests

from .cache import ResponseCache, build_cache_key
from .client import OpenWeatherMapError


LOGGER = logging.getLogger(__name__)
DEFAULT_GEOCODING_BASE_URL = "https://api.openweathermap.org/geo/1.0/direct"
GEOCODING_CACHE_KEY_PREFIX = "openweathermap:geocoding:v1:cache:v1:response"


class OpenWeatherMapGeocodingClient:
    """Resolve worldwide place names through OpenWeatherMap Direct Geocoding."""

    def __init__(
        self,
        api_key: str | None,
        *,
        base_url: str = DEFAULT_GEOCODING_BASE_URL,
        timeout_seconds: float = 10.0,
        session: requests.Session | None = None,
        cache: ResponseCache | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        self.api_key = api_key
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()
        self.cache = cache

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    @property
    def cache_enabled(self) -> bool:
        return self.cache is not None

    def search(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        """Return matching locations in OpenWeatherMap relevance order."""
        query = " ".join(query.split())
        if not query:
            raise OpenWeatherMapError(
                "A city name is required",
                status_code=400,
            )
        if not 1 <= limit <= 5:
            raise ValueError("limit must be between 1 and 5")
        if not self.api_key:
            raise OpenWeatherMapError(
                "OpenWeatherMap API key is not configured",
                status_code=503,
            )

        request_params: dict[str, Any] = {"q": query, "limit": limit}
        cache_key: str | None = None
        if self.cache is not None:
            try:
                cache_key = build_cache_key(
                    "direct",
                    request_params,
                    key_prefix=GEOCODING_CACHE_KEY_PREFIX,
                )
                cached_payload = self.cache.get(cache_key)
                if cached_payload is not None:
                    return self._validate_payload(cached_payload)
            except Exception as error:
                LOGGER.warning(
                    "OpenWeatherMap geocoding cache read failed; using upstream (%s)",
                    type(error).__name__,
                )

        try:
            response = self.session.get(
                self.base_url,
                params={**request_params, "appid": self.api_key},
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as error:
            raise OpenWeatherMapError(
                "Unable to reach OpenWeatherMap geocoding",
                status_code=502,
            ) from error
        try:
            payload = response.json()
        except ValueError as error:
            raise OpenWeatherMapError(
                "OpenWeatherMap geocoding returned an invalid response",
                status_code=502,
                details={"upstream_status": response.status_code},
            ) from error
        if not response.ok:
            status_code = response.status_code if response.status_code < 500 else 502
            raise OpenWeatherMapError(
                "OpenWeatherMap geocoding request failed",
                status_code=status_code,
                details={"upstream_status": response.status_code},
            )

        locations = self._validate_payload(payload)
        if self.cache is not None and cache_key is not None:
            try:
                self.cache.set(cache_key, locations)
            except Exception as error:
                LOGGER.warning(
                    "OpenWeatherMap geocoding cache write failed; returning upstream response (%s)",
                    type(error).__name__,
                )
        return locations

    @staticmethod
    def _validate_payload(payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, list) or not all(
            isinstance(item, dict) for item in payload
        ):
            raise OpenWeatherMapError(
                "OpenWeatherMap geocoding returned an invalid response",
                status_code=502,
            )
        return payload
