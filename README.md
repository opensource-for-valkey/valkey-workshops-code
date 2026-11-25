# Valkey Workshops Code

Hands-on applications, exercises, and supporting assets for learning caching patterns with [Valkey](https://valkey.io/). The repository's primary workshop uses an airport data application to demonstrate how a cache can improve performance, protect downstream systems, and support data structures beyond basic key-value lookups.

## What's in this repository

| Path | Description |
| --- | --- |
| [`workshops/`](workshops/) | Authoritative code samples for the Workshop Studio guides: one independent `uv` project per module, built on native Valkey GLIDE. |
| [`cache_me_if_you_can/`](cache_me_if_you_can/) | Primary Python workshop, interactive airport application, guided exercises, supporting services, and optional demos. |
| [`docs/`](docs/) | Shared FlughafenDB schema and correction SQL used by the workshop. |
| [`infra/`](infra/) | Optional Ubuntu bootstrap script for workshop prerequisites. Review the script before running it on your system. |

## Workshop topics

The primary workshop covers practical caching and Valkey use cases, including:

- Cache-aside, write-through, and write-behind patterns
- Cache stampede prevention
- Sorted-set leaderboards
- Semantic caching and vector search
- Natural-language-to-SQL workflows
- Cache transport safety, health checks, and operational controls
- Performance considerations for multithreaded workloads

See the [workshop README](cache_me_if_you_can/README.md) and [documentation index](cache_me_if_you_can/docs/README.md) for the complete learning path.

## Applications and demos

The `cache_me_if_you_can` workshop contains several runnable components:

| Component | Purpose |
| --- | --- |
| [`airport_app.py`](cache_me_if_you_can/airport_app.py) | Main Streamlit application for exploring airport data and caching patterns. |
| [`hands_on/`](cache_me_if_you_can/hands_on/) | Guided workshop exercises and implementations. |
| [`session_demo/`](cache_me_if_you_can/session_demo/) | Flask session-caching demonstration. |
| [`openweathermap_api/`](cache_me_if_you_can/openweathermap_api/) | Flask proxy for OpenWeatherMap One Call API 4.0. |
| [`jdbc-caching-demo/`](cache_me_if_you_can/jdbc-caching-demo/) | Full-stack JDBC caching demonstration with separate backend and frontend applications. |

Each substantial demo has its own README with configuration and startup instructions.

## Quick start

### Prerequisites

The automated setup checks for, but does not install:

- Docker Desktop or Docker Engine with a running daemon
- [Ollama](https://ollama.com/download)
- Python 3.13 or later
- [`uv`](https://docs.astral.sh/uv/)

Database-backed exercises also require MySQL, MariaDB, or PostgreSQL. The quickstart script does not manage the relational database.

### Automated local setup

Preview the required actions without making changes:

```bash
./quickstart.sh --dry-run
```

Prepare the workshop:

```bash
./quickstart.sh
```

The script safely and repeatedly:

- Checks Docker, Ollama, Python, and `uv`
- Starts `valkey/valkey:9-alpine` on `localhost:6380`
- Starts `valkey/valkey-bundle:9-alpine` on `localhost:16379`
- Starts Ollama when needed and pulls the `codellama` model
- Creates `cache_me_if_you_can/.env` when absent and updates only local service settings that need reconciliation
- Installs the locked Python dependencies with `uv sync --frozen`

Existing containers with conflicting names, images, or ports are left untouched. The script reports the conflict so you can resolve it explicitly.

### Manual setup

To configure the Python workshop without the root script:

```bash
cd cache_me_if_you_can
uv sync --frozen
cp .env.example .env
```

Update `.env` for your database, cache, and optional integrations. The file can contain credentials and is intentionally excluded from version control. Destructive cache clearing is disabled by default; only enable it for an isolated local workshop cache.

### Run the airport application

From `cache_me_if_you_can`:

```bash
uv run streamlit run airport_app.py
```

For more workshop-specific guidance, see [`cache_me_if_you_can/QUICKSTART.md`](cache_me_if_you_can/QUICKSTART.md).

## Test the Python workshop

From `cache_me_if_you_can`:

```bash
uv run pytest -q
```

## Repository layout

```text
valkey-workshops-code/
├── quickstart.sh             # Idempotent local workshop setup
├── cache_me_if_you_can/
│   ├── core/                 # Database, in-memory, and semantic-search helpers
│   ├── daos/                 # Caching-pattern data access implementations
│   ├── docs/                 # Concepts, implementation notes, and workshop guides
│   ├── hands_on/             # Guided exercises
│   ├── jdbc-caching-demo/    # Java/backend and web/frontend caching demo
│   ├── openweathermap_api/   # OpenWeatherMap One Call API proxy
│   ├── services/             # Supporting application services
│   ├── session_demo/         # Flask session-caching demo
│   ├── tests/                # Python test suite
│   └── airport_app.py        # Main Streamlit application
├── docs/                     # Shared SQL schema assets
└── infra/                    # Environment bootstrap tooling
```

## Documentation

Start with these guides:

- [Primary workshop overview](cache_me_if_you_can/README.md)
- [Quick start](cache_me_if_you_can/QUICKSTART.md)
- [Workshop documentation index](cache_me_if_you_can/docs/README.md)
- [OpenWeatherMap API proxy](cache_me_if_you_can/openweathermap_api/README.md)
- [JDBC caching demo](cache_me_if_you_can/jdbc-caching-demo/README.md)

## Data and licensing

SQL schema assets may include their own attribution and licensing terms in file headers. This repository currently does not contain a repository-wide `LICENSE` file; review applicable terms before redistributing code or data.
