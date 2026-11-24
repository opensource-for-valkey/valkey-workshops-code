"""Orchestrate prompt normalization, prose interpretation, and caching."""

from __future__ import annotations

from copy import deepcopy
import logging
from threading import Lock
from time import perf_counter
from typing import Any

from .cache import CacheLookup, SemanticWeatherCache
from .interpreter import ProseWeatherInterpreter, WeatherInterpreter
from .normalizer import PromptNormalizer
from .weather import WeatherProvider


LOGGER = logging.getLogger(__name__)


class WeatherQuestionService:
    """Answer natural-language weather questions through two cache layers."""

    def __init__(
        self,
        normalizer: PromptNormalizer,
        weather_provider: WeatherProvider,
        semantic_cache: SemanticWeatherCache | None = None,
        interpreter: WeatherInterpreter | None = None,
    ) -> None:
        self.normalizer = normalizer
        self.weather_provider = weather_provider
        self.semantic_cache = semantic_cache
        self.interpreter = interpreter or ProseWeatherInterpreter()
        self._metrics = {
            "requests": 0,
            "exact_hits": 0,
            "semantic_hits": 0,
            "misses": 0,
            "weather_api_calls": 0,
            "interpretation_calls": 0,
            "embedding_calls": 0,
            "model_calls": 0,
            "avoided_weather_api_calls": 0,
            "avoided_interpretation_calls": 0,
            "avoided_embedding_calls": 0,
            "avoided_model_calls": 0,
            "cache_errors": 0,
        }
        self._metrics_lock = Lock()

    def ask(self, prompt: str, *, units: str = "metric") -> dict[str, Any]:
        started = perf_counter()
        intent = self.normalizer.normalize(prompt, units=units)
        self._increment("requests")

        exact = self._get_exact(intent.normalized_prompt)
        if exact is not None:
            self._increment(
                "exact_hits",
                "avoided_weather_api_calls",
                "avoided_interpretation_calls",
                "avoided_embedding_calls",
                "avoided_model_calls",
            )
            return self._response(exact, intent, started)

        semantic_probe = None
        if self.semantic_cache is not None:
            try:
                self._increment("embedding_calls", "model_calls")
                semantic_probe = self.semantic_cache.find_semantic(
                    intent.normalized_prompt,
                    intent,
                )
                if semantic_probe.lookup is not None:
                    self.semantic_cache.link_exact(
                        intent.normalized_prompt,
                        semantic_probe.lookup.answer,
                    )
                    self._increment(
                        "semantic_hits",
                        "avoided_weather_api_calls",
                        "avoided_interpretation_calls",
                    )
                    return self._response(semantic_probe.lookup, intent, started)
            except Exception as error:
                self._cache_error("semantic lookup", error)

        self._increment("misses", "weather_api_calls", "interpretation_calls")
        weather = self.weather_provider.fetch(intent)
        prose = self.interpreter.interpret(intent, weather)
        answer = {
            "prose": prose,
            "location": intent.location.to_dict(),
            "period": {
                "label": intent.period,
                "start_at": intent.start_at.isoformat(),
                "end_at": intent.end_at.isoformat(),
                "granularity": intent.granularity,
            },
            "units": intent.units,
        }

        if self.semantic_cache is not None and semantic_probe is not None:
            try:
                self.semantic_cache.store(
                    intent.normalized_prompt,
                    intent.original_prompt,
                    intent,
                    answer,
                    semantic_probe.embedding,
                )
            except Exception as error:
                self._cache_error("interpreted answer cache write", error)

        return self._response(
            CacheLookup(answer=answer, cache_type="miss"),
            intent,
            started,
        )

    def metrics(self) -> dict[str, Any]:
        with self._metrics_lock:
            snapshot = dict(self._metrics)
        hits = snapshot["exact_hits"] + snapshot["semantic_hits"]
        snapshot["cache_hits"] = hits
        snapshot["hit_rate"] = (
            round(hits / snapshot["requests"], 4) if snapshot["requests"] else 0.0
        )
        if self.semantic_cache is not None:
            try:
                snapshot["interpreted_cache_items"] = self.semantic_cache.stats()
            except Exception as error:
                LOGGER.warning("Unable to read cache stats: %s", type(error).__name__)
                snapshot["interpreted_cache_items"] = None
        return snapshot

    def clear_cache(self) -> int:
        if self.semantic_cache is None:
            raise RuntimeError("interpreted answer cache is not configured")
        return self.semantic_cache.clear()

    def _get_exact(self, normalized_prompt: str) -> CacheLookup | None:
        if self.semantic_cache is None:
            return None
        try:
            return self.semantic_cache.get_exact(normalized_prompt)
        except Exception as error:
            self._cache_error("exact interpreted answer lookup", error)
            return None

    def _response(
        self,
        lookup: CacheLookup,
        intent: Any,
        started: float,
    ) -> dict[str, Any]:
        answer = deepcopy(lookup.answer)
        return {
            "prose": answer["prose"],
            "query": {
                "original_prompt": intent.original_prompt,
                "normalized_prompt": intent.normalized_prompt,
                "resolved_intent": intent.to_dict(),
            },
            "cache": {
                "hit": lookup.cache_type != "miss",
                "type": lookup.cache_type,
                "similarity": (
                    round(lookup.similarity, 4)
                    if lookup.similarity is not None
                    else None
                ),
                "matched_prompt": lookup.matched_prompt,
            },
            "latency_ms": round((perf_counter() - started) * 1000, 3),
            "metrics": self.metrics(),
        }

    def _cache_error(self, operation: str, error: Exception) -> None:
        self._increment("cache_errors")
        LOGGER.warning(
            "GenAI weather %s failed; continuing without it (%s)",
            operation,
            type(error).__name__,
        )

    def _increment(self, *names: str) -> None:
        with self._metrics_lock:
            for name in names:
                self._metrics[name] += 1
