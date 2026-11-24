"""Native synchronous GLIDE clients and binary-safe module command helpers."""

from __future__ import annotations

import atexit
import os
from functools import lru_cache
from threading import RLock
from typing import Iterator
from collections.abc import Mapping
from urllib.parse import unquote, urlparse

from dotenv import load_dotenv
from glide_sync import (
    GlideClient,
    GlideClientConfiguration,
    NodeAddress,
    ProtocolVersion,
    ServerCredentials,
)


class ValkeyClientManager:
    """Own one GLIDE connection; close it at context exit or process shutdown."""

    def __init__(
        self,
        *,
        env_prefix: str = "VALKEY",
        fallback_prefix: str | None = None,
        default_port: int = 6379,
        url: str | None = None,
        request_timeout_ms: int = 5000,
    ) -> None:
        load_dotenv(os.environ.get("WORKSHOP_ENV_FILE", ".env"), override=False)
        prefixes = [env_prefix]
        if fallback_prefix:
            prefixes.append(fallback_prefix)
        if "VALKEY" not in prefixes:
            prefixes.append("VALKEY")

        def setting(suffix: str, default: str | None = None) -> str | None:
            return next(
                (
                    os.environ[f"{prefix}_{suffix}"]
                    for prefix in prefixes
                    if os.environ.get(f"{prefix}_{suffix}")
                ),
                default,
            )

        host = setting("HOST", "127.0.0.1")
        port = int(setting("PORT", str(default_port)))
        database = int(setting("DB", "0"))
        password = setting("PASSWORD")
        username = setting("USERNAME", "default")
        use_tls = setting("TLS", "false").casefold() in {"true", "1", "yes"}
        if url:
            parsed = urlparse(url)
            if parsed.scheme not in {"valkey", "valkeys", "redis", "rediss"}:
                raise ValueError("Use a valkey:// or valkeys:// endpoint URL")
            host = parsed.hostname or host
            port = parsed.port or port
            database = int(parsed.path.strip("/") or "0")
            password = unquote(parsed.password) if parsed.password else password
            username = unquote(parsed.username) if parsed.username else username
            use_tls = parsed.scheme in {"valkeys", "rediss"}
        self.configuration = GlideClientConfiguration(
            addresses=[NodeAddress(host, port)],
            credentials=(
                ServerCredentials(password=password, username=username)
                if password
                else None
            ),
            database_id=database,
            use_tls=use_tls,
            request_timeout=request_timeout_ms,
            # Search returns a document mapping; vector values remain bytes.
            protocol=ProtocolVersion.RESP2,
            lazy_connect=True,
        )
        self._client: GlideClient | None = None
        self._lock = RLock()
        atexit.register(self.close)

    @property
    def client(self) -> GlideClient:
        with self._lock:
            if self._client is None:
                self._client = GlideClient.create(self.configuration)
            return self._client

    def close(self) -> None:
        with self._lock:
            if self._client is not None:
                self._client.close()
                self._client = None

    def __enter__(self) -> ValkeyClientManager:
        _ = self.client
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


@lru_cache(maxsize=16)
def get_client_manager(
    env_prefix: str = "VALKEY", default_port: int = 6379
) -> ValkeyClientManager:
    """Share an explicitly owned client within a CLI or application process."""
    return ValkeyClientManager(env_prefix=env_prefix, default_port=default_port)


def scan_keys(client: GlideClient, pattern: str, count: int = 100) -> Iterator[bytes]:
    cursor: bytes | str = "0"
    while True:
        cursor, keys = client.scan(cursor, match=pattern, count=count)
        yield from keys
        if cursor in {b"0", "0", 0}:
            return


def search_document_keys(
    client: GlideClient, index: str, vector: bytes, candidates: int
) -> list[bytes]:
    """Issue binary FLOAT32 KNN parameters directly through GLIDE."""
    response = client.custom_command(
        [
            "FT.SEARCH",
            index,
            f"*=>[KNN {candidates} @embedding $vector AS vector_distance]",
            "NOCONTENT",
            "PARAMS",
            "2",
            "vector",
            vector,
            "LIMIT",
            "0",
            str(candidates),
            "DIALECT",
            "2",
        ]
    )
    return search_reply_keys(response)


def search_reply_keys(response) -> list[bytes]:
    """Return document keys from an FT.SEARCH reply.

    GLIDE returns ``[total, {key: fields}]`` from Valkey Bundle 9.2. Other
    servers and protocols return the positional form ``[total, key, ...]``
    with NOCONTENT, or ``[total, key, fields, ...]`` with content.
    """
    if not response or int(response[0]) == 0:
        return []
    entries = response[1:]
    if len(entries) == 1 and isinstance(entries[0], Mapping):
        return list(entries[0])
    if len(entries) > 1 and all(isinstance(entry, list) for entry in entries[1::2]):
        return list(entries[::2])
    if all(isinstance(entry, (bytes, str)) for entry in entries):
        return list(entries)
    raise TypeError("Unexpected Valkey Search reply shape")


def decode_text(value: bytes | str | None) -> str | None:
    return value.decode("utf-8") if isinstance(value, bytes) else value
