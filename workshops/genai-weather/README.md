Runnable native GLIDE reference for the GenAI weather workshop. Python 3.13 and
uv are required. The application uses OpenWeatherMap's API, exact prompt
pointers, and FLOAT32 semantic vectors with Valkey JSON and Search.

```bash
uv sync --locked
uv run python setup_env.py
```

Edit the private `.env` and add `OPENWEATHERMAP_API_KEY`. For an existing workshop
service, use its native password and endpoint. For a local server:

```bash
docker compose up -d --wait
docker compose exec -T valkey valkey-cli PING
uv run python -m cache_me_if_you_can_genai
```

The public lab API listens on loopback port 5001 by default. The independent raw
weather proxy is available with `uv run python -m openweathermap_api` on loopback
port 5000. Cache clearing is disabled by default. Each client is owned by
`ValkeyClientManager`; its process shutdown hook closes the connection. Logging
and startup output use Rich. Models load lazily on the first embedding request.

Source models, HTTP clients, normalization, and interpretation were adapted from
the `opensource-for-valkey/valkey-workshops-code` project. The native
GLIDE client and module-command migration lives in this repository. Upstream does not currently publish a repository license file; this attribution makes no additional license claim.

`setup_env.py` preserves a configured password, then uses an exported password or
a provisioned `.valkey.env` found beside the private environment, in an ancestor,
or under `~/workshop`. `WORKSHOP_CREDENTIALS_FILE` can select the credential file
explicitly. A random local password is generated only when none is available.
