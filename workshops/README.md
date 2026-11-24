# Workshop code samples

This directory is the authoritative source for the code used by the
[Valkey workshop guides](https://github.com/opensource-for-valkey/valkey-workshops-studio).
The workshop CloudFormation stacks clone this repository to `~/workshop/valkey`,
so each project below is available at `~/workshop/valkey/workshops/<project>`.

| Project | Guide module |
| --- | --- |
| [`baseline-cache/`](baseline-cache/) | Cache me if you can; From Cache-Aside to Semantic Cache |
| [`recommendations/`](recommendations/) | Recommendations with Valkey Search |
| [`genai-weather/`](genai-weather/) | Cache me if you can: GenAI edition |
| [`semantic-faq/`](semantic-faq/) | From Cache-Aside to Semantic Cache |
| [`valkey-data-structures/`](valkey-data-structures/) | High-performance data structures |
| [`python-common/`](python-common/) | Shared `ValkeyClientManager` and GLIDE helpers |

Each project is an independent Python 3.13 `uv` project with its own
`pyproject.toml` and `uv.lock`:

```bash
cd ~/workshop/valkey/workshops/baseline-cache
uv sync --locked
uv run --locked python setup_env.py
```

`setup_env.py` creates a private `.env` (mode `0600`). Never commit `.env`.

Workshop instances run authenticated Valkey containers on loopback and keep
their shared password in `~/workshop/.valkey.env` (mode `0600`):

| Container | Port | Used for |
| --- | --- | --- |
| `valkey-cache` | 6379 | Exact caching (`VALKEY_*`) |
| `valkey-server` | 6380 | Additional plain Valkey server |
| `valkey-bundle` | 16379 | Search and JSON (`VECTOR_*`, GenAI, FAQ) |

Except in `valkey-data-structures`, `setup_env.py` copies that password into
`.env`. On a workshop instance, use these services and skip the projects'
`docker compose up` commands. Away from a workshop instance, `setup_env.py`
generates a random password that the Compose files then require.

Integration tests that need a real Valkey server live in [`tests/`](tests/) and
run in CI; see `.github/workflows/ci.yml`.
