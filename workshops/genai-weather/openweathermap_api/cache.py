"""Valkey JSON cache-aside support for OpenWeatherMap responses."""

from __future__ import annotations
from glide_sync import Batch
from valkey_client_manager import scan_keys
import hashlib
import json
import time
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol
from urllib.parse import quote

CACHE_DOCUMENT_SCHEMA_VERSION = 1
CACHE_KEY_PREFIX = "openweathermap:onecall:v4:cache:v1:response"


class ResponseCache(Protocol):
    """Cache operations required by the OpenWeatherMap HTTP client."""

    def get(self, key: str) -> Any | None: ...

    def set(self, key: str, payload: Any) -> None: ...

    def clear(self) -> int: ...


def _canonical_coordinate(value: Any) -> str:
    try:
        coordinate = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"Invalid coordinate for cache key: {value!r}") from error
    if not coordinate.is_finite():
        raise ValueError(f"Invalid coordinate for cache key: {value!r}")
    if coordinate == 0:
        coordinate = Decimal(0)
    return format(coordinate.normalize(), "f")


def _canonical_value(name: str, value: Any) -> Any:
    if name in {"lat", "lon"}:
        return _canonical_coordinate(value)
    if isinstance(value, dict):
        return {
            str(key).lower(): _canonical_value(str(key).lower(), nested_value)
            for key, nested_value in sorted(
                value.items(), key=lambda item: str(item[0])
            )
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_value(name, item) for item in value]
    if isinstance(value, bool):
        return "true" if value else "false"
    if name in {"units", "lang"} and isinstance(value, str):
        return value.lower()
    return str(value)


def canonical_request(path: str, params: dict[str, Any]) -> dict[str, Any]:
    """Return the normalized, secret-free request identity used by cache keys."""
    canonical_params = {
        key.lower(): _canonical_value(key.lower(), value)
        for key, value in sorted(params.items(), key=lambda item: item[0].lower())
        if value is not None and key.lower() != "appid"
    }
    canonical_path = "/".join(
        (segment for segment in path.strip("/").split("/") if segment)
    )
    return {"path": canonical_path, "params": canonical_params}


def build_cache_key(
    path: str, params: dict[str, Any], *, key_prefix: str = CACHE_KEY_PREFIX
) -> str:
    """Build a versioned taxonomic key from a canonical request identity."""
    request_identity = canonical_request(path, params)
    canonical_json = json.dumps(
        request_identity, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    query_digest = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    resource = ":".join(
        (quote(segment, safe="-_.") for segment in request_identity["path"].split("/"))
    )
    key_parts = [key_prefix, resource]
    canonical_params = request_identity["params"]
    if "lat" in canonical_params and "lon" in canonical_params:
        key_parts.extend(
            ["location", f"{{{canonical_params['lat']},{canonical_params['lon']}}}"]
        )
    key_parts.extend(["query", query_digest])
    return ":".join(key_parts)


class ValkeyJsonCache:
    """Store OpenWeatherMap responses as JSON documents with a fixed TTL."""

    def __init__(
        self, client: Any, ttl_seconds: int = 600, *, key_prefix: str = CACHE_KEY_PREFIX
    ) -> None:
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int):
            raise TypeError("ttl_seconds must be an integer")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be greater than zero")
        if not key_prefix:
            raise ValueError("key_prefix must not be empty")
        self.client = client
        self.ttl_seconds = ttl_seconds
        self.key_prefix = key_prefix

    def get(self, key: str) -> Any | None:
        raw = self.client.custom_command(["JSON.GET", key, "$"])
        if raw is None:
            return None
        document = json.loads(raw)
        if isinstance(document, list) and len(document) == 1:
            document = document[0]
        if not isinstance(document, dict):
            raise ValueError("Cached OpenWeatherMap document is not an object")
        if document.get("schema_version") != CACHE_DOCUMENT_SCHEMA_VERSION:
            raise ValueError("Cached OpenWeatherMap document has an unknown schema")
        if "payload" not in document:
            raise ValueError("Cached OpenWeatherMap document has no payload")
        return document["payload"]

    def set(self, key: str, payload: Any) -> None:
        document = {
            "schema_version": CACHE_DOCUMENT_SCHEMA_VERSION,
            "cached_at": int(time.time()),
            "payload": payload,
        }
        pipeline = Batch(is_atomic=True)
        pipeline.custom_command(["JSON.SET", key, "$", json.dumps(document)])
        pipeline.expire(key, self.ttl_seconds)
        results = self.client.exec(pipeline, raise_on_error=True)
        if len(results) < 2 or not results[0] or (not results[1]):
            raise RuntimeError("Valkey JSON cache write did not complete")

    def clear(self) -> int:
        """Remove only OpenWeatherMap response keys using incremental scans."""
        pattern = f"{self.key_prefix}:*"
        batch: list[Any] = []
        cleared_items = 0
        for key in scan_keys(self.client, pattern=pattern, count=100):
            batch.append(key)
            if len(batch) == 100:
                cleared_items += int(self.client.unlink(batch))
                batch.clear()
        if batch:
            cleared_items += int(self.client.unlink(batch))
        return cleared_items
