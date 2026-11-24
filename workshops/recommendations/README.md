Native GLIDE movie Search reference and notebook. The small movie corpus uses
synthetic vectors so Search, prefix suggestions, trending queries, and KNN
recommendations run without downloading an embedding model.

```bash
uv python install 3.13
uv sync --locked
uv run python setup_env.py
```

Configure the authenticated Search-capable Valkey Bundle endpoint in private
`.env`. Then run `uv run python search_demo.py` or open
`valkey_search_workshop.ipynb` with this project's uv-managed Python kernel.
`ValkeyClientManager` closes native GLIDE connections at context exit, loads
`WORKSHOP_ENV_FILE` or the current directory's `.env`, and preserves native bytes
for vectors. Results are displayed using Rich.

Keys are limited to `workshop:movies:v1:*`, and the Search index is
`workshop_movies_v1`. These examples create or update only that namespace.
Production recommendations need representative vectors, tenant filtering,
rank evaluation, and a defined indexing freshness budget.

`setup_env.py` preserves a configured password, then uses an exported password or
a provisioned `.valkey.env` found beside the private environment, in an ancestor,
or under `~/workshop`. `WORKSHOP_CREDENTIALS_FILE` can select the credential file
explicitly. A random local password is generated only when none is available.
