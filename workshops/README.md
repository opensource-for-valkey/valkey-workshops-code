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

`setup_env.py` creates a private `.env` (mode `0600`). Except in
`valkey-data-structures`, it reuses the provisioned `~/workshop/.valkey.env`
password when present. Never commit `.env`.

Integration tests that need a real Valkey server live in [`tests/`](tests/) and
run in CI; see `.github/workflows/ci.yml`.
