"""Project-scoped cache values backed by the native synchronous GLIDE client."""

from __future__ import annotations

import os
import re
from typing import Any

from glide_sync import ExpirySet, ExpiryType

from valkey_client_manager import ValkeyClientManager, decode_text, scan_keys


class InMemoryCache:
    """Own a GLIDE connection and a prefix; expose cache-domain operations."""

    def __init__(
        self,
        cache_type: str | None = None,
        host: str | None = None,
        port: int | None = None,
        decode_responses: bool = True,
        **kwargs: Any,
    ) -> None:
        self.manager = ValkeyClientManager(env_prefix="CACHE", fallback_prefix="VALKEY")
        self.cache_type = cache_type or os.getenv("CACHE_ENGINE", "valkey")
        if self.cache_type not in {"valkey", "redis"}:
            raise ValueError("This workshop uses native Valkey GLIDE")
        self.prefix = os.getenv("CACHE_KEY_PREFIX", "baseline:attendee:")
        if not re.fullmatch(r"[A-Za-z0-9:_{}-]+:", self.prefix):
            raise ValueError("CACHE_KEY_PREFIX must be a nonempty literal prefix ending in ':'")
        address = self.manager.configuration.addresses[0]
        self.host = host or address.host
        self.port = port or address.port
        if host is not None or port is not None:
            self.manager.close()
            self.manager = ValkeyClientManager(
                env_prefix="CACHE",
                fallback_prefix="VALKEY",
                url=f"valkey://{self.host}:{self.port}",
            )
        if kwargs:
            raise TypeError(f"Unsupported cache settings: {', '.join(kwargs)}")
        self.decode_responses = decode_responses

    @property
    def client(self):
        """Return the native GLIDE client for batches and structured commands."""
        return self.manager.client

    def key(self, logical_key: str) -> str:
        return logical_key if logical_key.startswith(self.prefix) else self.prefix + logical_key

    def get(self, key: str) -> str | bytes | None:
        value = self.client.get(self.key(key))
        return decode_text(value) if self.decode_responses else value

    def set(self, key: str, value: str, ttl: int | None = None) -> bool:
        expiry = ExpirySet(ExpiryType.SEC, ttl) if ttl is not None else None
        return self.client.set(self.key(key), value, expiry=expiry) == "OK"

    def delete(self, key: str) -> bool:
        return bool(self.client.delete([self.key(key)]))

    def keys(self, pattern: str = "*") -> list[str]:
        return [key.decode() for key in scan_keys(self.client, self.key(pattern))]

    def flush_all(self) -> int:
        """Retain the sample API name, but delete only this project's prefix."""
        removed = 0
        for key in scan_keys(self.client, self.prefix + "*"):
            removed += self.client.unlink([key])
        return removed

    def close(self) -> None:
        self.manager.close()

    def __enter__(self):
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def get_cache_client(**kwargs: Any) -> InMemoryCache:
    return InMemoryCache(**kwargs)
