# Baseline cache workshop runtime

This local project keeps the Airport, cache-aside, write-through, write-behind,
weather, leaderboard, concurrency, stampede and Flask session entrypoints used
in the caching workshop. Every Python Valkey connection uses the native
synchronous GLIDE client through `ValkeyClientManager`.

Run from this directory:

```bash
uv sync --locked
uv run python setup_env.py
uv run python samples/demo_cache_aside.py --help
uv run streamlit run airport_app.py
uv run python -m session_demo.app
```

Edit the private `.env` to match the provisioned Valkey and relational services.
`python-dotenv` loads it automatically; do not source it into the shell.
`SECRET_KEY` signs the Flask session ID. Session data remains in Valkey as tagged
JSON and expires after 31 days. Login/logout rotate the ID. The demo selects a
passenger by passport; it does not implement production login authentication.
Both web apps listen on `127.0.0.1` by default.

The base environment does not download an embedding model or PyTorch. The SQL
semantic demo additionally requires the Valkey Search bundle, Ollama with the
configured model, and the optional model dependencies:

```bash
uv sync --locked --extra semantic
uv run python samples/demo_semantic_cache.py --help
```

The sample `--flush` option clears only the literal `CACHE_KEY_PREFIX`
(`baseline:attendee:` by default). It never issues `FLUSHDB` or `FLUSHALL`.
Choose a distinct prefix for each participant. The write-behind demo has a
single-worker recovery design and at-least-once task delivery; coordinate worker
ownership before reclaiming processing tasks.

Run the meaningful native integration checks against an existing authenticated
Valkey instance:

```bash
uv sync --locked --group test
uv run pytest
```

Set `WORKSHOP_ENV_FILE` to a private configuration path when testing another
instance. Integration checks skip when no configured Valkey password is present.

Source attribution: adapted from the `cache_me_if_you_can` project in
https://github.com/opensource-for-valkey/valkey-workshops-code (branch `main`).
The source's existing copyright and file-specific notices are retained. This
adaptation replaces Redis-py/Valkey-py and Flask-Session integration with native
GLIDE, scopes cache clearing, adds private configuration and tests, and makes
model loading lazy. No new project license is asserted here.
