Runnable native GLIDE reference for the managed Valkey FAQ semantic-cache lab.
Python 3.13 and uv are required. The curated `data/*-faq.md` files are included; `SEMANTIC_FAQ_DATA_DIR` can select another corpus.

```bash
uv sync --locked
uv run python setup_env.py
```

For an existing service, configure its endpoint and native password. For a local
Search-capable service:

```bash
docker compose up -d --wait
docker compose exec -T valkey valkey-cli PING
uv run python -m semantic_cache
```

The public workshop API defaults to `127.0.0.1:8000`, prints startup details using
Rich, and closes its `ValkeyClientManager` during application shutdown. Cache
clearing is disabled by default. JSON payloads and binary FLOAT32 vectors use
native GLIDE commands; no Redis client adapter is required.

`WORKSHOP_ENV_FILE` selects a different private environment file. Otherwise
python-dotenv loads `.env` from the current directory. Never publish `.env`.

The curated FAQ corpus is copied from the public `opensource-for-valkey/valkey-workshops-code` project (`cache_me_if_you_can/data`); source URLs and attribution remain in the files. This makes no additional license claim.

`setup_env.py` preserves a configured password, then uses an exported password or
a provisioned `.valkey.env` found beside the private environment, in an ancestor,
or under `~/workshop`. `WORKSHOP_CREDENTIALS_FILE` can select the credential file
explicitly. A random local password is generated only when none is available.
