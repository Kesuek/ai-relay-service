# Docker

Container setups for the AI-Relay-Service. Each deployment lives in its own
subdirectory.

## Available setups

| Directory | What | Status |
|---|---|---|
| [`server/`](server/) | Relay server (SQLite or PostgreSQL) | ✅ available |
| [`nodes/base/`](nodes/base/) | Reusable node base image (installed node stack) | ✅ available |
| [`nodes/storage/`](nodes/storage/) | Storage service node (NAS-backed, real handlers + bridge server) | ✅ available |

## Server

The server setup builds the relay server as a container. It supports two
database backends:

- **SQLite** (default) — DB file in the named volume `relay-data`
- **PostgreSQL** — external host **or** bundled `postgres` container
  (`--profile postgres`)

Quick start (from the repo root):

```bash
cp docker/server/.env.example .env   # set seed + secrets
docker compose -f docker/server/docker-compose.yml up -d --build
```

Full guide, DB choice, and troubleshooting:
[`docs/server/docker.md`](../docs/server/docker.md)

## Special nodes

Specialized nodes (storage, SSN, …) run as containers built from a shared
**base image** plus a thin per-service layer. The base image carries the
installed node stack (node-daemon, relay_client, handler_runner); a service
image only adds its `node.yaml` + `handlers/` directory.

### Base image (`base/`)

A reusable image that installs the node stack from the project wheel. A
service image builds `FROM ai-relay-node-base` and only adds its capability
profile + handlers — no Python install, no wheel build.

```bash
# Build once (from the repo root):
docker build -t ai-relay-node-base -f docker/nodes/base/Dockerfile .
```

The entrypoint translates environment variables into the files the node stack
reads from `~/.relay` (`relay_config.json`, `node.yaml`, meta + token) and
registers the node on first start, then execs `node-daemon` (SSE,
event-driven).

#### Environment variables

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `RELAY_URL` | **yes** | — | Relay base URL, e.g. `https://relay.example.com` |
| `NODE_NAME` | no | container hostname | Human-friendly node name |
| `NODE_PROFILE` | no | — | Profile name in `profiles.d/` to publish to `node.yaml` |
| `NODE_ROLE` | no | `worker` | Node role: `worker` or `service` |
| `NODE_ENDPOINT` | no | — | Upstream endpoint the relay can reach this node on |
| `NODE_REGISTRATION_SECRET` | no | — | Pre-created `rs_...` secret for the register call |
| `RELAY_HEARTBEAT_INTERVAL` | no | `8` | Heartbeat interval (seconds) |
| `RELAY_CLAIM_INTERVAL` | no | `5` | Claim poll interval (seconds) |
| `RELAY_REQUEST_TIMEOUT` | no | `10` | HTTP request timeout (seconds) |
| `RELAY_LOG_LEVEL` | no | `INFO` | Log level (DEBUG/INFO/WARNING/ERROR) |

Fail-fast: the entrypoint exits with an error when `RELAY_URL` is unset.

### Adding a new service node

A new special node is a new `docker/nodes/<service>/` directory with at minimum:

```
docker/nodes/<service>/
├── Dockerfile        # FROM ai-relay-node-base; COPY node.yaml + handlers/
├── node.yaml         # capability declarations for this service
├── handlers/         # executable scripts the daemon runs per claimed stage
└── docker-compose.yml  # example compose (external relay)
```

The Dockerfile is typically ~10 lines — it only layers the profile + handlers
onto the base image and sets `NODE_PROFILE` + `NODE_ROLE`. See
[`nodes/storage/Dockerfile`](nodes/storage/Dockerfile) for a reference.

### Storage node (`nodes/storage/`)

The storage node is a NAS-backed service node with **real handlers**
(Plan B / Phase 30): `storage.store` / `fetch` / `delete` / `list` /
`quota` / `stat` / `move` plus the bridge channel capabilities
`storage.upload_channel` / `storage.download_channel` for large-file
streaming. It also runs a small **bridge server** (`bridge_server.py`)
alongside the daemon that the relay proxies large-file requests to,
gated by a Source-IP-Allowlist so only the relay can reach it.

```bash
# 1. Build the base image (see above).
# 2. Build the storage image:
docker build -t ai-relay-storage -f docker/nodes/storage/Dockerfile .
# 3. Run against your relay:
RELAY_URL=https://relay.example.com \
STORAGE_DIR=/mnt/nas/relay-storage \
docker compose -f docker/nodes/storage/docker-compose.yml up -d
```

The node registers on first start (status=`pending`) — approve it via the
relay dashboard or `relay-recovery admin approve-node <node_id>`. State
(meta + token) persists in the `storage-state` volume so the node keeps its
identity across restarts. The bridge server listens on `0.0.0.0:8791`
inside the container; set `RELAY_SERVER_IP` in the compose env when the
relay's IP is not resolvable from the `RELAY_URL` hostname (e.g. a
Tailscale IP).

See [`docs/node/storage.md`](../docs/node/storage.md) for the full
architecture, handler reference, and bridge channel flow.