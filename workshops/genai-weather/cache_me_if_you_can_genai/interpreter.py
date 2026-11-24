"""Convert structured OpenWeatherMap records into concise bot replies."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Protocol

import pycountry

from .models import WeatherIntent


class WeatherInterpreter(Protocol):
    """Interpret structured weather data as a natural-language answer."""

    def interpret(self, intent: WeatherIntent, weather: dict[str, Any]) -> str: ...


class ProseWeatherInterpreter:
    """Produce deterministic prose from OpenWeatherMap timeline records."""

    def interpret(self, intent: WeatherIntent, weather: dict[str, Any]) -> str:
        records = self._flatten_records(weather.get("records", []))
        location = self._location_text(intent)
        period = self._period_text(intent)
        if not records:
            return (
                f"The weather in {location} {period} is unavailable because "
                "OpenWeatherMap returned no records for the requested period."
            )

        descriptions = self._descriptions(records)
        condition = descriptions[0] if descriptions else self._cloud_condition(records)
        condition = condition or "available"
        condition_text, emoji = self._condition_style(condition)
        reply = (
            f"The weather in {location} {period} is {condition_text} {emoji}".strip()
        )

        temperatures = self._temperatures(records)
        if temperatures:
            reply += self._temperature_phrase(temperatures, intent.units, len(records))
        reply += "."

        if len(descriptions) > 1:
            alternatives = [
                self._condition_style(value)[0] for value in descriptions[1:3]
            ]
            reply += f" Conditions may also include {self._join(alternatives)}."

        humidity = self._numeric_values(records, "humidity")
        if humidity:
            reply += (
                f" Average humidity is {round(sum(humidity) / len(humidity))} percent."
            )

        precipitation = self._numeric_values(records, "pop")
        if precipitation:
            maximum_probability = max(precipitation)
            if maximum_probability <= 1:
                maximum_probability *= 100
            reply += (
                " The highest chance of precipitation is "
                f"{round(maximum_probability)} percent."
            )
        return reply

    @staticmethod
    def _location_text(intent: WeatherIntent) -> str:
        country_code = intent.location.country.upper()
        country_record = pycountry.countries.get(alpha_2=country_code)
        country = (
            getattr(country_record, "name", country_code)
            if country_record is not None
            else country_code
        )
        flag = (
            getattr(country_record, "flag", None)
            if country_record is not None
            else None
        ) or "".join(chr(127397 + ord(letter)) for letter in country_code)
        parts = [intent.location.name]
        if intent.location.region and intent.location.region.casefold() not in {
            intent.location.name.casefold(),
            country.casefold(),
        }:
            parts.append(intent.location.region)
        parts.append(country)
        return f"{', '.join(parts)} {flag}".strip()

    def _period_text(self, intent: WeatherIntent) -> str:
        label = "today" if intent.period == "today (default)" else intent.period
        if intent.granularity == "current":
            return f"right now, {self._full_date(intent.start_at.date())},"
        if intent.period == "this afternoon":
            return (
                f"this afternoon, {self._full_date(intent.start_at.date())}, "
                f"from {self._time(intent.start_at)} to {self._time(intent.end_at)},"
            )
        if (intent.end_at - intent.start_at).days == 1:
            return f"{label}, {self._full_date(intent.start_at.date())},"
        final_date = intent.end_at.date() - timedelta(days=1)
        return (
            f"for {label}, from {self._full_date(intent.start_at.date())} "
            f"through {self._full_date(final_date)},"
        )

    def _descriptions(self, records: list[dict[str, Any]]) -> list[str]:
        descriptions: list[str] = []
        for record in records:
            description = self._description(record)
            if description and description not in descriptions:
                descriptions.append(description)
        return descriptions

    @staticmethod
    def _description(record: dict[str, Any]) -> str | None:
        weather = record.get("weather")
        if isinstance(weather, list) and weather and isinstance(weather[0], dict):
            value = weather[0].get("description") or weather[0].get("main")
            if value:
                return str(value).casefold()
        if isinstance(weather, dict):
            value = weather.get("description") or weather.get("main")
            if value:
                return str(value).casefold()
        for name in ("description", "summary", "condition"):
            value = record.get(name)
            if value:
                return str(value).casefold()
        return None

    @staticmethod
    def _cloud_condition(records: list[dict[str, Any]]) -> str | None:
        percentages: list[float] = []
        for record in records:
            value = record.get("cloud_cover", record.get("clouds"))
            if isinstance(value, dict):
                value = value.get("all")
            if isinstance(value, (int, float)):
                percentages.append(float(value))
        if not percentages:
            return None
        average = sum(percentages) / len(percentages)
        if average <= 10:
            return "clear"
        if average <= 40:
            return "partly cloudy"
        return "cloudy"

    @staticmethod
    def _condition_style(description: str) -> tuple[str, str]:
        normalized = description.casefold()
        if "thunder" in normalized:
            return "stormy", "⛈️"
        if "snow" in normalized:
            return "snowy", "🌨️"
        if "rain" in normalized or "drizzle" in normalized:
            return "rainy", "🌧️"
        if any(word in normalized for word in ("fog", "mist", "haze", "smoke")):
            return "foggy", "🌫️"
        if "cloud" in normalized or "overcast" in normalized:
            return "cloudy", "⛅"
        if "clear" in normalized or "sun" in normalized:
            return "clear", "☀️"
        return normalized, "🌤️"

    def _temperatures(self, records: list[dict[str, Any]]) -> list[float]:
        values: list[float] = []
        for record in records:
            candidate = record.get("temp", record.get("temperature"))
            if candidate is None and isinstance(record.get("main"), dict):
                candidate = record["main"].get("temp")
            if isinstance(candidate, dict):
                preferred = [candidate.get(name) for name in ("min", "max", "day")]
                values.extend(
                    float(value)
                    for value in preferred
                    if isinstance(value, (int, float))
                )
            elif isinstance(candidate, (int, float)):
                values.append(float(candidate))
        return values

    @staticmethod
    def _temperature_phrase(
        values: list[float],
        units: str,
        record_count: int,
    ) -> str:
        unit = {
            "metric": "degrees Celsius",
            "imperial": "degrees Fahrenheit",
            "standard": "kelvin",
        }[units]
        minimum = min(values)
        maximum = max(values)
        if record_count == 1 or abs(maximum - minimum) < 0.005:
            return f" at {ProseWeatherInterpreter._number(maximum)} {unit}"
        return (
            f", with temperatures from {ProseWeatherInterpreter._number(minimum)} "
            f"to {ProseWeatherInterpreter._number(maximum)} {unit}"
        )

    @staticmethod
    def _numeric_values(records: list[dict[str, Any]], name: str) -> list[float]:
        values = []
        for record in records:
            value = record.get(name)
            if value is None and isinstance(record.get("main"), dict):
                value = record["main"].get(name)
            if isinstance(value, (int, float)):
                values.append(float(value))
        return values

    @staticmethod
    def _flatten_records(values: Any) -> list[dict[str, Any]]:
        if not isinstance(values, list):
            return []
        records: list[dict[str, Any]] = []
        for value in values:
            if not isinstance(value, dict):
                continue
            nested = value.get("data")
            if isinstance(nested, list):
                records.extend(item for item in nested if isinstance(item, dict))
            else:
                records.append(value)
        return records

    @staticmethod
    def _full_date(value: date) -> str:
        return (
            f"{value.strftime('%A %B')} {ProseWeatherInterpreter._ordinal(value.day)}, "
            f"{value.year}"
        )

    @staticmethod
    def _ordinal(day: int) -> str:
        if 10 < day % 100 < 14:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
        return f"{day}{suffix}"

    @staticmethod
    def _time(value: Any) -> str:
        return (
            f"{value.strftime('%I:%M %p').lstrip('0')} {value.tzname() or ''}".strip()
        )

    @staticmethod
    def _number(value: float) -> str:
        return f"{value:.2f}".rstrip("0").rstrip(".")

    @staticmethod
    def _join(values: list[str]) -> str:
        if len(values) == 1:
            return values[0]
        if len(values) == 2:
            return f"{values[0]} and {values[1]}"
        return f"{', '.join(values[:-1])}, and {values[-1]}"
