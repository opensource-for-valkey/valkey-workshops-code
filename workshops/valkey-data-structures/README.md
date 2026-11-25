# Building High-Performance Architectures with Valkey Data Structures

Runnable references for the CLI follow-along guide in
`content/07-high-performance-data-structures`. The guide explains each command
before Python, provides complete files in collapsed sections, and includes
collapsed checkpoint responses.

Requirements: `uv`, Docker, and Docker Compose with `up --wait` support.
Python 3.13 is selected by `.python-version`.

## Start the environment

From this directory:

```bash
uv sync --locked
uv run --locked python setup_env.py
docker compose up -d --wait
uv run --locked python common.py
```

`setup_env.py` generates a random password in a private `.env`; it does not print
or replace credentials. New files select `VALKEY_MODE=standalone`,
`VALKEY_TLS=false`, and database `0`. Docker Compose reads `.env` automatically.
`python-dotenv` reads the selected private file for every Python program,
without overriding process variables. You do not need to activate a virtual
environment or export the file's contents. Keep private profiles out of
version control.

`ValkeyClientManager` in `valkey_client.py` configures standalone, Sentinel, or
Cluster connections and owns their native synchronous GLIDE clients. It closes
them when a program's `with` block ends. Clients return bytes; `common.text()`
handles decoding at the application boundary. Rich formats the CLI output, and
Textual powers the live terminal dashboard.

The server uses `valkey/valkey:9.2-alpine`, password authentication, AOF, and
`noeviction`. Its host port is `127.0.0.1:6381`. Valkey Admin uses the pinned
`valkey/valkey-admin:1.2.0` image in Web mode, on `127.0.0.1:8082`.
Change `VALKEY_PORT` / `VALKEY_ADMIN_PORT` in `.env` if those ports are occupied.

## Inspect commands in Valkey Admin

Open `http://localhost:8082`. Add a connection with host **valkey**, port
**6379**, password authentication, user **default**, and the password from your
private `.env`. Explicitly clear **Use TLS** in the connection form. The host is the Compose service name because Admin runs inside
the container network. In **Send Command**, verify `PING` and `INFO server`.

Start with Key/Value foundations: `SET`, `GET`, `TYPE`, key names, lifetimes,
expiration, and removal. Then follow the String, Hash, Sorted Set, Pub/Sub, and
List commands in this console before implementing each program. The full
curriculum takes about four hours; the guide also lists a two-hour conference
path. The local server is dedicated to your workshop. Examples use the plain
`ds:` prefix to group keys for inspection and cleanup.
If your browser is on another machine, forward the Admin port to your browser's
machine.

## Read response latency

Every functional response reports measured milliseconds. The shared monotonic
clock measures client-observed operations; initial client creation and console rendering
are outside command timings. Sentinel rediscovery or reconnection inside a call
is included. Failed cache calls retain their elapsed time.

Cache responses separate total request time, Valkey GET, the simulated
20 ms source-of-truth read, and cache SET. A warm hit marks the skipped source
and write phases as `not used`. Compare cold, warm, and invalidated requests,
then use the sampled p50/p95 comparison; the source is a demonstration, rather
than a real database benchmark.

Session and leaderboard queries, event publication, queue commands, readiness,
and key cleanup report their own times. Queue claim latency includes
blocking wait. Pub/Sub event age uses UTC clocks and may include clock offset
and subscriber polling delay; it is separate from the measured local dequeue
call. The dashboard shows a latency column for every query plus PING and total
refresh timings. Values vary with workload, network, and deployment mode.

## Run the patterns

```bash
uv run --locked python cache.py
uv run --locked python sessions.py
uv run --locked python leaderboard.py
```

Explore file bytes, compressed binary values, UTF-8 byte ranges, JSON, and YAML:

```bash
uv run --locked python binary_strings.py
```

The bundled `assets/valkey-horizontal.svg` is the requested Valkey logo. Its SVG
content is XML text; the program also stores a compressed copy and a payload
containing NUL and non-UTF-8 bytes. It checks byte-for-byte round trips and reports
the latency of `SET`, `GET`, `STRLEN`, `TYPE`, and `OBJECT ENCODING`. Valkey stores
bytes; Python performs decoding, parsing, and decompression.

In another terminal, watch stored state with the read-only dashboard:

```bash
uv run --locked python dashboard.py
```

Press **r** to refresh or **q** to quit.

For Pub/Sub, open two terminals in this directory and run this command in each:

```bash
uv run --locked python events.py subscribe
```

Wait for both `READY` messages, then publish in a third terminal:

```bash
uv run --locked python events.py publish
```

Stop both subscribers and publish again to observe zero subscribers and no
offline replay. Valkey Admin can also send `PUBLISH`; its ordinary command
console is not a persistent subscriber.

For the reliable List queue:

```bash
uv run --locked python queues.py enqueue
uv run --locked python queues.py work --worker worker-a --crash-after-claim
# The deliberate crash exits with status 2.
uv run --locked python queues.py inspect
uv run --locked python queues.py recover --worker worker-a --stopped
uv run --locked python queues.py work --worker worker-a
uv run --locked python queues.py inspect
```

Use one unique worker ID per process. `--stopped` asserts that you stopped the
worker; it does not detect liveness. A worker exits after two seconds without a
ready task. To observe duplicate delivery, enqueue another job and run with
`--crash-after-effect`, then recover and retry. The demonstration effect uses
`HSETNX`; an external effect needs its own durable idempotency mechanism.

## Measure and clean up

After stopping the subscribers and workers:

```bash
uv run --locked python benchmark.py
uv run --locked python cleanup.py
docker compose down --volumes
```

The benchmark compares 500 increments sequentially and in GLIDE batches over
five repeats. Cleanup uses `SCAN` and `UNLINK` on the configured key prefix.
The default `VALKEY_KEY_PREFIX=ds` matches `ds:*`; keys with other prefixes remain.
Queue keys such as `ds:queue:{reports}:ready` retain the static `{reports}` hash tag
so related keys share a Cluster slot for `LMOVE` and `BLMOVE`. Ordinary workshop
keys need no hash tag.

AOF with `appendfsync everysec` and List processing state do not guarantee that
every acknowledged task survives a server crash or failover. Production queues
also need worker ownership, liveness or leases, retries, dead-letter handling,
capacity monitoring, and an appropriate persistence policy.

## Verification

The test group is independent of the repository root environment:

```bash
uv sync --locked --group test
uv run --locked --group test python -m pytest -q tests
VALKEY_WORKSHOP_INTEGRATION=1 uv run --locked --group test \
  python -m pytest -q ../tests/test_data_structures_workshop.py
```

The first test command checks connection configuration and client lifecycle
without starting containers. Integration tests use unique key prefixes and
verify real GLIDE commands, expiry,
authentication errors, Pub/Sub fanout, crash recovery, duplicate effects,
scoped cleanup, binary round trips, and Textual's actual widget updates.

## Connection profiles

The default Compose environment remains the local standalone profile. The
following profiles connect to existing TLS, Sentinel, or Cluster deployments.
Their provisioning and certificates are supplied by that deployment's owner.

Select a private profile with `VALKEY_ENV_FILE`; it takes precedence over the
compatible `WORKSHOP_ENV_FILE` setting. With neither variable set, programs use
`.env` beside `valkey_client.py`. Exported settings take precedence over file
values. A profile can be selected for one command without exporting credentials:

```bash
VALKEY_ENV_FILE="$PWD/.env.cluster" uv run --locked python common.py
```

Use the same selection in every terminal. `setup_env.py` also honors
`VALKEY_ENV_FILE`, followed by `WORKSHOP_ENV_FILE`. It creates a new private file
with local defaults; an existing profile retains its values.

| Setting | Default | Meaning |
|---|---|---|
| `VALKEY_MODE` | `standalone` | `standalone`, `sentinel`, or `cluster` |
| `VALKEY_HOST` / `VALKEY_PORT` | `127.0.0.1` / `6381` | Standalone endpoint when `VALKEY_NODES` is empty |
| `VALKEY_NODES` | Empty | Comma-separated data-node seeds, such as `host-a:6379,host-b:6379`; required for Cluster |
| `VALKEY_USERNAME` / `VALKEY_PASSWORD` | `default` / required | Native Valkey data-node credentials in every mode |
| `VALKEY_DATABASE` | `0` | Logical database; Cluster requires `0` |
| `VALKEY_REQUEST_TIMEOUT_MS` | `5000` | Request timeout, including Sentinel control requests |
| `VALKEY_CONNECTION_TIMEOUT_MS` | `3000` | Connection timeout, including Sentinel control connections |
| `VALKEY_CLIENT_NAME` | `valkey-data-structures-workshop` | Native client name |
| `VALKEY_KEY_PREFIX` | `ds` | Plain application naming prefix, matching the Admin exercises |
| `VALKEY_TLS` | `false` | TLS for data-node connections |
| `VALKEY_TLS_CA_CERT` | Empty | PEM CA file; empty uses system trust |
| `VALKEY_TLS_CLIENT_CERT` / `VALKEY_TLS_CLIENT_KEY` | Empty | Client certificate and private key for mutual TLS; provide both |

Use `[::1]:6379` for an IPv6 seed. Certificate paths are relative to the selected
profile's directory. TLS verifies the server certificate and hostname. Its
certificate must cover the data-node addresses discovered through Sentinel or
advertised by a Cluster.

Sentinel discovery uses a separate connection to the monitoring nodes:

| Setting | Default | Meaning |
|---|---|---|
| `VALKEY_SENTINEL_NODES` | Required in Sentinel mode | Comma-separated Sentinel endpoints, typically port `26379` |
| `VALKEY_SENTINEL_SERVICE` | Required in Sentinel mode | Monitored primary's service name |
| `VALKEY_SENTINEL_USERNAME` / `VALKEY_SENTINEL_PASSWORD` | `default` / empty | Sentinel credentials; empty password selects unauthenticated Sentinel control connections |
| `VALKEY_SENTINEL_TLS` | Value of `VALKEY_TLS` | TLS for discovery; can differ from data-node TLS |
| `VALKEY_SENTINEL_TLS_CA_CERT` | Empty | Sentinel CA file; empty uses system trust |
| `VALKEY_SENTINEL_TLS_CLIENT_CERT` / `VALKEY_SENTINEL_TLS_CLIENT_KEY` | Empty | Sentinel mutual TLS certificate/key pair |
| `VALKEY_SENTINEL_REFRESH_MS` | `1000` | Interval between primary rediscovery checks before calls |

Sentinel credentials and certificate paths do not inherit the data-node
credentials or certificate paths. Only its TLS boolean follows `VALKEY_TLS`
when no Sentinel TLS override is set. The data-node user's ACL must allow `ROLE`
for primary verification, and the monitoring user's ACL must allow
`SENTINEL get-master-addr-by-name`.

Edit a private profile to match your deployment. These examples use
placeholders; replace them with provisioned endpoints and credentials.

For plaintext data connections in any mode, set `VALKEY_TLS=false` and leave
all three `VALKEY_TLS_*` certificate paths empty. For plaintext Sentinel
discovery, also set `VALKEY_SENTINEL_TLS=false` and leave its certificate paths
empty; monitoring connections can independently retain TLS when required.

Standalone with TLS:

```dotenv
VALKEY_MODE=standalone
VALKEY_HOST=cache.internal.example
VALKEY_PORT=6379
VALKEY_USERNAME=default
VALKEY_PASSWORD=<data-password>
VALKEY_TLS=true
VALKEY_TLS_CA_CERT=certs/data-ca.pem
VALKEY_KEY_PREFIX=ds
```

Cluster with TLS:

```dotenv
VALKEY_MODE=cluster
VALKEY_NODES=cache-a.internal.example:6379,cache-b.internal.example:6379
VALKEY_USERNAME=default
VALKEY_PASSWORD=<data-password>
VALKEY_DATABASE=0
VALKEY_TLS=true
VALKEY_TLS_CA_CERT=certs/data-ca.pem
VALKEY_KEY_PREFIX=ds
```

Sentinel with separately authenticated TLS discovery and TLS data nodes:

```dotenv
VALKEY_MODE=sentinel
VALKEY_SENTINEL_NODES=sentinel-a.internal.example:26379,sentinel-b.internal.example:26379
VALKEY_SENTINEL_SERVICE=workshop-primary
VALKEY_SENTINEL_USERNAME=default
VALKEY_SENTINEL_PASSWORD=<sentinel-password>
VALKEY_SENTINEL_TLS=true
VALKEY_SENTINEL_TLS_CA_CERT=certs/sentinel-ca.pem
VALKEY_USERNAME=default
VALKEY_PASSWORD=<data-password>
VALKEY_TLS=true
VALKEY_TLS_CA_CERT=certs/data-ca.pem
VALKEY_KEY_PREFIX=ds
```

Keep each private profile and private key local, with file mode `0600`. The queue keys use `ds:queue:{reports}:...`; their `{reports}` hash tag keeps
multi-key List moves in one Cluster slot. Other keys have ordinary names.
`VALKEY_KEY_PREFIX` defaults to `ds`; tests can override it for cleanup isolation.

GLIDE 2.6 has no native Sentinel client. The manager discovers and validates the
primary through native GLIDE control connections, checks for promotions before
calls, and reconnects without replaying a failed write. Pub/Sub polling also
rediscovers the primary and recreates subscriptions; messages lost during that
gap are not replayed. A Cluster `PUBLISH` reply counts subscriptions on the
publishing node, rather than total delivery across the cluster.
