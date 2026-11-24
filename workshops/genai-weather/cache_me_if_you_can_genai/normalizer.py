"""Normalize natural-language weather periods into explicit local times."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
import re
from zoneinfo import ZoneInfo

from .locations import LocationResolver
from .models import WeatherIntent


class PromptNormalizationError(ValueError):
    """Raised when a weather prompt cannot be normalized safely."""


@dataclass(frozen=True)
class _ResolvedPeriod:
    matched_text: str | None
    token: str
    start_at: datetime
    end_at: datetime
    granularity: str
    label: str


_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
}


class PromptNormalizer:
    """Resolve a supported city and relative period without invoking an LLM."""

    def __init__(
        self,
        location_resolver: LocationResolver | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.location_resolver = location_resolver or LocationResolver()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def normalize(self, prompt: str, *, units: str = "metric") -> WeatherIntent:
        prompt = prompt.strip()
        if not prompt:
            raise PromptNormalizationError("prompt must not be empty")
        if units not in {"standard", "metric", "imperial"}:
            raise PromptNormalizationError(
                "units must be standard, metric, or imperial"
            )

        resolved_location = self.location_resolver.resolve(prompt)
        zone = ZoneInfo(resolved_location.location.timezone)
        current = self.clock()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        local_now = current.astimezone(zone)
        period = self._resolve_period(prompt, local_now)

        normalized = re.sub(
            rf"(?<!\w){re.escape(resolved_location.matched_alias)}(?!\w)",
            f"location:{resolved_location.location.location_id}",
            prompt.casefold(),
            count=1,
            flags=re.IGNORECASE,
        )
        if period.matched_text:
            normalized = re.sub(
                re.escape(period.matched_text),
                period.token,
                normalized,
                count=1,
                flags=re.IGNORECASE,
            )
        else:
            normalized = f"{normalized} {period.token}"
        normalized = re.sub(r"[^\w:/+\-.]+", " ", normalized)
        normalized = " ".join(normalized.split())
        normalized = f"{normalized} units:{units}"

        return WeatherIntent(
            original_prompt=prompt,
            normalized_prompt=normalized,
            location=resolved_location.location,
            start_at=period.start_at,
            end_at=period.end_at,
            granularity=period.granularity,
            period=period.label,
            units=units,
        )

    def _resolve_period(
        self,
        prompt: str,
        local_now: datetime,
    ) -> _ResolvedPeriod:
        local_midnight = datetime.combine(
            local_now.date(),
            time.min,
            tzinfo=local_now.tzinfo,
        )

        afternoon = re.search(r"\bthis\s+afternoon\b", prompt, re.IGNORECASE)
        if afternoon:
            noon = local_midnight.replace(hour=12)
            evening = local_midnight.replace(hour=18)
            if noon <= local_now < evening:
                start_at = local_now.replace(second=0, microsecond=0)
            else:
                start_at = noon
            return _ResolvedPeriod(
                matched_text=afternoon.group(0),
                token=f"time:{start_at.isoformat()}/{evening.isoformat()}",
                start_at=start_at,
                end_at=evening,
                granularity="hourly",
                label="this afternoon",
            )

        next_week = re.search(r"\bnext\s+week\b", prompt, re.IGNORECASE)
        if next_week:
            days_until_next_monday = 7 - local_midnight.weekday()
            start_at = local_midnight + timedelta(days=days_until_next_monday)
            end_at = start_at + timedelta(days=7)
            return self._date_range(next_week.group(0), start_at, end_at, "next week")

        next_days = re.search(
            r"\bnext\s+(?P<count>\d+|" + "|".join(_NUMBER_WORDS) + r")\s+days?\b",
            prompt,
            re.IGNORECASE,
        )
        if next_days:
            raw_count = next_days.group("count").casefold()
            count = int(raw_count) if raw_count.isdigit() else _NUMBER_WORDS[raw_count]
            if not 1 <= count <= 14:
                raise PromptNormalizationError(
                    "relative day ranges must contain between 1 and 14 days"
                )
            return self._date_range(
                next_days.group(0),
                local_midnight,
                local_midnight + timedelta(days=count),
                f"next {count} days",
            )

        now_match = re.search(r"\bnow\b", prompt, re.IGNORECASE)
        if now_match:
            start_at = local_now.replace(second=0, microsecond=0)
            end_at = start_at + timedelta(minutes=1)
            return _ResolvedPeriod(
                matched_text=now_match.group(0),
                token=f"time:{start_at.isoformat()}",
                start_at=start_at,
                end_at=end_at,
                granularity="current",
                label="now",
            )

        relative_days = (
            (r"\byesterday\b", -1, "yesterday", "hourly"),
            (r"\btomorrow\b", 1, "tomorrow", "daily"),
            (r"\btoday\b", 0, "today", "daily"),
        )
        for pattern, offset, label, granularity in relative_days:
            match = re.search(pattern, prompt, re.IGNORECASE)
            if match:
                start_at = local_midnight + timedelta(days=offset)
                end_at = start_at + timedelta(days=1)
                return _ResolvedPeriod(
                    matched_text=match.group(0),
                    token=f"date:{start_at.date().isoformat()}",
                    start_at=start_at,
                    end_at=end_at,
                    granularity=granularity,
                    label=label,
                )

        return _ResolvedPeriod(
            matched_text=None,
            token=f"date:{local_midnight.date().isoformat()}",
            start_at=local_midnight,
            end_at=local_midnight + timedelta(days=1),
            granularity="daily",
            label="today (default)",
        )

    @staticmethod
    def _date_range(
        matched_text: str,
        start_at: datetime,
        end_at: datetime,
        label: str,
    ) -> _ResolvedPeriod:
        last_date = (end_at - timedelta(days=1)).date().isoformat()
        return _ResolvedPeriod(
            matched_text=matched_text,
            token=f"range:{start_at.date().isoformat()}/{last_date}",
            start_at=start_at,
            end_at=end_at,
            granularity="daily",
            label=label,
        )
