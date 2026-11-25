"""Resolve workshop aliases and arbitrary worldwide cities."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Any, Protocol
import unicodedata

from .models import Location


LOCATIONS = (
    Location(
        location_id="mexico-city-mx",
        name="Mexico City",
        country="MX",
        latitude=19.4326,
        longitude=-99.1332,
        timezone="America/Mexico_City",
        aliases=(
            "mexico city, mexico",
            "mexico city",
            "ciudad de méxico",
            "ciudad de mexico",
            "cdmx",
        ),
    ),
    Location(
        location_id="buenos-aires-ar",
        name="Buenos Aires",
        country="AR",
        latitude=-34.6037,
        longitude=-58.3816,
        timezone="America/Argentina/Buenos_Aires",
        aliases=("buenos aires, argentina", "buenos aires argentina", "buenos aires"),
    ),
    Location(
        location_id="new-york-city-us",
        name="New York City",
        country="US",
        latitude=40.7128,
        longitude=-74.0060,
        timezone="America/New_York",
        aliases=("new york city", "new york", "nyc"),
    ),
)


class GeocodingClient(Protocol):
    """Operations required from a worldwide place-name geocoder."""

    def search(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]: ...


class CoordinateTimezoneFinder(Protocol):
    """Resolve an IANA timezone from geographic coordinates."""

    def timezone_at(self, *, lng: float, lat: float) -> str | None: ...


class UnknownLocationError(ValueError):
    """Raised when a prompt does not identify a resolvable city."""


@dataclass(frozen=True)
class ResolvedLocation:
    location: Location
    matched_alias: str


class LocationResolver:
    """Resolve known aliases first, then geocode arbitrary city names."""

    _PERIOD_SUFFIX = re.compile(
        r"\s+(?:yesterday|today|tomorrow|now|this\s+afternoon|next\s+week|"
        r"next\s+(?:\d+|[a-z]+)\s+days?)\b.*$",
        re.IGNORECASE,
    )

    def __init__(
        self,
        locations: tuple[Location, ...] = LOCATIONS,
        *,
        geocoder: GeocodingClient | None = None,
        timezone_finder: CoordinateTimezoneFinder | None = None,
    ) -> None:
        if (geocoder is None) != (timezone_finder is None):
            raise ValueError("geocoder and timezone_finder must be configured together")
        self.locations = locations
        self.geocoder = geocoder
        self.timezone_finder = timezone_finder
        self._aliases = sorted(
            ((alias, location) for location in locations for alias in location.aliases),
            key=lambda item: len(item[0]),
            reverse=True,
        )

    def resolve(self, prompt: str) -> ResolvedLocation:
        for alias, location in self._aliases:
            if re.search(
                rf"(?<!\w){re.escape(alias)}(?!\w)",
                prompt,
                flags=re.IGNORECASE,
            ):
                return ResolvedLocation(location=location, matched_alias=alias)

        if self.geocoder is None or self.timezone_finder is None:
            supported = ", ".join(location.name for location in self.locations)
            raise UnknownLocationError(
                f"No supported city was found. Try one of: {supported}"
            )

        query = self._extract_query(prompt)
        matches = self.geocoder.search(query, limit=5)
        if not matches:
            raise UnknownLocationError(
                f"No city matching '{query}' was found. "
                "Try including its state or province and country."
            )
        location = self._to_location(matches[0], query)
        return ResolvedLocation(location=location, matched_alias=query)

    def _to_location(self, match: dict[str, Any], query: str) -> Location:
        name = match.get("name")
        country = match.get("country")
        latitude = match.get("lat")
        longitude = match.get("lon")
        if (
            not isinstance(name, str)
            or not name.strip()
            or not isinstance(country, str)
            or len(country.strip()) != 2
            or not isinstance(latitude, (int, float))
            or not isinstance(longitude, (int, float))
        ):
            raise UnknownLocationError(
                "OpenWeatherMap returned an incomplete location match"
            )

        timezone = self.timezone_finder.timezone_at(
            lng=float(longitude),
            lat=float(latitude),
        )
        if not timezone:
            raise UnknownLocationError(
                f"The timezone for '{query}' could not be determined"
            )

        state_value = match.get("state")
        state = state_value.strip() if isinstance(state_value, str) else None
        country_code = country.upper()
        canonical = "|".join(
            (
                name.strip().casefold(),
                (state or "").casefold(),
                country_code,
                f"{float(latitude):.4f}",
                f"{float(longitude):.4f}",
            )
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:10]
        slug = self._slug(f"{name}-{state or ''}-{country_code}")
        return Location(
            location_id=f"{slug}-{digest}",
            name=name.strip(),
            country=country_code,
            latitude=float(latitude),
            longitude=float(longitude),
            timezone=timezone,
            aliases=(query, name.strip()),
            region=state,
        )

    @classmethod
    def _extract_query(cls, prompt: str) -> str:
        prompt = " ".join(prompt.split())
        for preposition in ("in", "at", "for"):
            matches = list(
                re.finditer(
                    rf"\b{preposition}\s+(?P<location>.+)$",
                    prompt,
                    flags=re.IGNORECASE,
                )
            )
            for match in reversed(matches):
                candidate = cls._clean_candidate(match.group("location"))
                if candidate and not re.match(
                    r"^(?:today|tomorrow|yesterday|now|this\s+afternoon|next\b)",
                    candidate,
                    flags=re.IGNORECASE,
                ):
                    return candidate

        location_first = re.match(
            r"^\s*(?P<location>.+?)\s+(?:weather|forecast|temperature)\b",
            prompt,
            flags=re.IGNORECASE,
        )
        if location_first:
            candidate = cls._clean_candidate(location_first.group("location"))
            if candidate:
                return candidate

        raise UnknownLocationError(
            "No city was found in the prompt. Try 'What is the weather in Paris?'"
        )

    @classmethod
    def _clean_candidate(cls, candidate: str) -> str:
        candidate = cls._PERIOD_SUFFIX.sub("", candidate)
        candidate = re.sub(
            r"\s+(?:in\s+)?(?:metric|imperial|standard)\s+units?\b.*$",
            "",
            candidate,
            flags=re.IGNORECASE,
        )
        return candidate.strip(" \t\r\n?.!;:")

    @staticmethod
    def _slug(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value)
        ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
        slug = re.sub(r"[^a-z0-9]+", "-", ascii_value.casefold()).strip("-")
        return slug[:64] or "location"
