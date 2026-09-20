# Cache Me If You Can - Valkey Workshop

A hands-on workshop demonstrating caching patterns with Valkey/Redis and relational databases.

## Quick Start

### Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) package manager
- MySQL/MariaDB or PostgreSQL
- Valkey or Redis
- Docker, only when building the preloaded MariaDB image

### Installation

```bash
# Install uv if needed
curl -LsSf https://astral.sh/uv/install.sh | sh

# From this project directory
uv sync
```

### Configuration

```bash
cp .env.example .env
```

At minimum, configure the database and cache endpoints:

```bash
DB_ENGINE=mysql
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_password
DB_NAME=flughafendb_large

CACHE_ENGINE=valkey
CACHE_HOST=localhost
CACHE_PORT=6379
```

Cache authentication, TLS, database selection, timeouts, and health checks are available through `CACHE_USERNAME`, `CACHE_PASSWORD`, `CACHE_DB`, `CACHE_TLS`, `CACHE_TLS_CA_CERTS`, `CACHE_TLS_CERTFILE`, `CACHE_TLS_KEYFILE`, `CACHE_CONNECT_TIMEOUT`, `CACHE_SOCKET_TIMEOUT`, and `CACHE_HEALTH_CHECK_INTERVAL`.

Destructive cache clearing is disabled by default. Set `CACHE_ALLOW_FLUSH_ALL=true` only when the configured cache is isolated for workshop use.

### Database Setup

Import the checked-in database dump directly:

```bash
gunzip -c data/flughafendb_large_20260528_171359.sql.gz | mysql -u root -p
```

### Preloaded MariaDB Container Image

Use `scripts/create_preloaded_container.sh` as the supported image-generation workflow. It finds the newest `data/*.sql.gz` dump and imports it during the image build:

```bash
./scripts/create_preloaded_container.sh <registry-user>
```

The resulting image is tagged `<registry-user>/flughafendb_mariadb:latest`.

```bash
docker run -d \
  -p 127.0.0.1:3306:3306 \
  -e WORKSHOP_DB_USER=flughafen_user \
  -e WORKSHOP_DB_PASSWORD='<strong-password>' \
  --name flughafendb_mariadb \
  <registry-user>/flughafendb_mariadb:latest
```

`scripts/create_container_image.sh` remains as a compatibility entry point and delegates to the supported script. It no longer creates a different image or performs container lifecycle operations.

## Running the Applications

### Airport App

```bash
./scripts/run_airport_app.sh
# Or
uv run streamlit run airport_app.py
```

The application opens at <http://localhost:8501> and demonstrates cache-aside behavior, flight and passenger queries, performance metrics, and cache hit statistics.

### Session Demo

```bash
uv run python session_demo/app.py
```

Set `PORT` to change the default port of `5001`. Debug mode is disabled by default and can be enabled locally with `FLASK_DEBUG=true`.

### Demo Scripts

```bash
# Run all demos
./scripts/run_all_demos.sh

# Individual patterns
uv run python samples/demo_cache_aside.py
uv run python samples/demo_weather_api_cache.py
uv run python samples/demo_write_through_cache.py
uv run python samples/demo_write_behind_cache.py
uv run python samples/demo_stampede_prevention.py --threads 10 --cities 3
uv run python samples/demo_multi_threaded_performance.py --users 4 --queries 10
```

### NLP to SQL

```bash
uv run python daos/nlp_to_sql.py tinyllama interactive
uv run python daos/nlp_to_sql.py codellama
```

## Caching Patterns

### Cache-Aside

- Read from cache first.
- On a miss, read from the database.
- Populate the cache for later requests.

### Write-Through

- Write to the database first.
- Update the cache immediately afterward.
- Keep database state authoritative.

### Write-Behind

- Publish the cache update and queue task in one Valkey transaction.
- Move tasks to a processing list until the database transaction commits.
- Retry failures up to `WRITE_BEHIND_MAX_RETRIES`.
- Route exhausted or malformed tasks to `flight_updates_dead_letter`.
- Recover tasks left in `flight_updates_processing` after a worker interruption.

The write-behind worker is designed for one active workshop worker. Coordinate recovery before introducing concurrent workers.

### External API Caching and Stampede Prevention

- Cache expensive API calls with a TTL.
- Use distributed locking to prevent duplicate upstream requests.
- Propagate cache transport failures so they are not mistaken for misses or lock contention.

## Testing

The default suite uses local fakes and does not require running Valkey or a database:

```bash
uv sync
uv run pytest
```

The scripts named `tests/test_enhanced_context.py`, `tests/test_nlp_sql_pretty.py`, `tests/test_semantic_search.py`, and `tests/test_sql_cleaning.py` are manual validation utilities and are intentionally excluded from default pytest collection because they load models, external services, or demonstration output.

## Project Structure

```text
cache_me_if_you_can/
├── core/               # Database and cache connection managers
├── daos/               # Cache pattern and NLP data-access implementations
├── samples/            # Interactive pattern demonstrations
├── services/           # Supporting service layer
├── session_demo/       # Flask session-caching demonstration
├── tests/              # Isolated unit tests and manual validations
├── docs/               # Concepts, implementation notes, and workshop content
├── scripts/            # Application, database, and image utilities
├── airport_app.py      # Streamlit workshop application
└── pyproject.toml      # Runtime and development dependencies
```

## Core Modules

```python
from core import get_cache_client, get_db_engine

engine = get_db_engine()
cache = get_cache_client()
```

See [`core/README.md`](core/README.md) and [`docs/README.md`](docs/README.md) for additional documentation.

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `DB_ENGINE` | Database type: mysql, mariadb, or postgresql | `mysql` |
| `DB_HOST` | Database host | `localhost` |
| `DB_PORT` | Database port | `3306` |
| `DB_USER` | Database user | `root` |
| `DB_PASSWORD` | Database password | empty |
| `DB_NAME` | Database name | `flughafendb_large` |
| `CACHE_ENGINE` | Cache type: redis, valkey, or memcached | `redis` |
| `CACHE_HOST` | Cache host | `localhost` |
| `CACHE_PORT` | Cache port | `6379` |
| `CACHE_DB` | Redis/Valkey logical database | `0` |
| `CACHE_TTL` | Default TTL in seconds | `3600` |
| `CACHE_TLS` | Enable TLS with certificate verification | `false` |
| `CACHE_CONNECT_TIMEOUT` | Connection timeout in seconds | `5` |
| `CACHE_SOCKET_TIMEOUT` | Operation timeout in seconds | `5` |
| `CACHE_HEALTH_CHECK_INTERVAL` | Connection health-check interval | `30` |
| `CACHE_ALLOW_FLUSH_ALL` | Allow destructive workshop cache clearing | `false` |
| `WRITE_BEHIND_MAX_RETRIES` | Attempts before dead-lettering | `3` |
| `OLLAMA_MODEL` | Model used for NLP-to-SQL | `codellama` |
