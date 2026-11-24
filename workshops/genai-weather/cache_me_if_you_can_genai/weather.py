"""Translate normalized intents into OpenWeatherMap requests."""

from __future__ import annotations

from datetime import timezone
from typing import Any, Protocol

from openweathermap_api.client import OpenWeatherMapClient

from .models import WeatherIntent


class WeatherProvider(Protocol):
    @property
    def is_configured(self) -> bool: ...

    @property
    def response_cache_enabled(self) -> bool: ...

    def fetch(self, intent: WeatherIntent) -> dict[str, Any]: ...


class OpenWeatherMapWeatherProvider:
    """Fetch and trim One Call 4.0 responses to an intent's time window."""

    def __init__(self, client: OpenWeatherMapClient) -> None:
        self.client = client

    @property
    def is_configured(self) -> bool:
        return self.client.is_configured

    @property
    def response_cache_enabled(self) -> bool:
        return self.client.cache_enabled

    def fetch(self, intent: WeatherIntent) -> dict[str, Any]:
        params: dict[str, Any] = {
            "lat": intent.location.latitude,
            "lon": intent.location.longitude,
            "units": intent.units,
        }
        if intent.granularity == "current":
            return {
                "endpoint": "current",
                "records": [self.client.current(params)],
                "record_count": 1,
            }

        interval = "1h" if intent.granularity == "hourly" else "1day"
        params["start"] = int(intent.start_at.timestamp())
        payload = self.client.timeline(interval, params)
        return self._filter_timeline(payload, interval, intent)

    @staticmethod
    def _filter_timeline(
        payload: Any,
        interval: str,
        intent: WeatherIntent,
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {
                "endpoint": f"timeline/{interval}",
                "records": [],
                "record_count": 0,
                "upstream_payload": payload,
            }

        data = payload.get("data")
        if not isinstance(data, list):
            return {
                "endpoint": f"timeline/{interval}",
                "records": [],
                "record_count": 0,
                "upstream_payload": payload,
            }

        start_utc = intent.start_at.astimezone(timezone.utc).timestamp()
        end_utc = intent.end_at.astimezone(timezone.utc).timestamp()
        records = []
        for record in data:
            if not isinstance(record, dict):
                continue
            try:
                timestamp = float(record["dt"])
            except (KeyError, TypeError, ValueError):
                continue
            if start_utc <= timestamp < end_utc:
                records.append(record)

        metadata = {key: value for key, value in payload.items() if key != "data"}
        return {
            "endpoint": f"timeline/{interval}",
            "records": records,
            "record_count": len(records),
            "upstream_metadata": metadata,
        }
