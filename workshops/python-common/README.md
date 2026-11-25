Native GLIDE helpers for the Python workshops. `ValkeyClientManager` owns one
client, reads `WORKSHOP_ENV_FILE` (default `.env` in the current directory), and
closes the native connection at context exit or process shutdown.

```bash
uv sync --locked --group test
uv run python - <<'PY'
from rich.console import Console
from valkey_client_manager import ValkeyClientManager

with ValkeyClientManager() as manager:
    Console().print(manager.client.ping().decode())
PY
```

Use `manager.client` with the synchronous GLIDE APIs. Replies are bytes; decode
text at the presentation boundary and preserve binary vectors. Search and JSON
use binary-safe `custom_command` arguments; atomic changes use `Batch`.

Set `VALKEY_HOST`, `VALKEY_PORT`, `VALKEY_PASSWORD`, `VALKEY_USERNAME`,
`VALKEY_DB`, and `VALKEY_TLS` as needed. Application prefixes override these
shared settings. Never commit `.env`. Set an existing service's native password
in your private environment; do not disable its authentication.

From the repository root, run the shared helper tests:

```bash
uv run --locked --project workshops/python-common --group test python -m pytest -q workshops/python-common/tests
```

The JSON, FAQ, and weather integration cases are skipped by default. Set
`VALKEY_LEGACY_INTEGRATION=1` and `WORKSHOP_ENV_FILE` to a private environment
containing the authenticated bundle endpoint to run them. They use small fake
embeddings, isolated key prefixes, and temporary indexes; no model or weather
API access is required.
