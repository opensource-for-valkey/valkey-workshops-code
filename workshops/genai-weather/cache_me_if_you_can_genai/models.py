"""Data models for normalized weather questions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Location:
    """A supported city with coordinates and an IANA time zone."""

    location_id: str
    name: str
    country: str
    latitude: float
    longitude: float
    timezone: str
    aliases: tuple[str, ...]
    region: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.location_id,
            "name": self.name,
            "country": self.country,
            "region": self.region,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "timezone": self.timezone,
        }


@dataclass(frozen=True)
class WeatherIntent:
    """A prompt resolved to a location and an explicit time window."""

    original_prompt: str
    normalized_prompt: str
    location: Location
    start_at: datetime
    end_at: datetime
    granularity: str
    period: str
    units: str

    @property
    def constraints(self) -> dict[str, str]:
        """Fields that must match before a semantic result can be reused."""
        return {
            "location_id": self.location.location_id,
            "start_at": self.start_at.isoformat(),
            "end_at": self.end_at.isoformat(),
            "granularity": self.granularity,
            "units": self.units,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "location": self.location.to_dict(),
            "period": self.period,
            "start_at": self.start_at.isoformat(),
            "end_at": self.end_at.isoformat(),
            "granularity": self.granularity,
            "units": self.units,
        }
