"""
Core module for connection management.

Provides centralized connection factories for:
- RDBMS (MySQL, MariaDB, PostgreSQL) via SQLAlchemy
- In-Memory Caches (Redis, Valkey, Memcached)
"""

from .rdbms import (
    RDBMSConnection,
    get_db_engine,
    get_db_connection,
    quote_identifier,
)
from .inmemory import InMemoryCache, get_cache_client

__all__ = [
    "RDBMSConnection",
    "get_db_engine",
    "get_db_connection",
    "quote_identifier",
    "InMemoryCache",
    "get_cache_client",
]
