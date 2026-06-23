# AI-Relay-Service v2

Standalone agent cluster server for distributed AI agents. The core focuses on
**connection, authentication, task distribution, and availability monitoring**.
Domain services like Board, Vault, or Activity run as external nodes with their
own capabilities and register with the relay over a public v2 API.

- **Port:** 8788
- **Framework:** FastAPI + uvicorn
- **DB:** SQLite + WAL (`~/.relay/server.db`)
- **Auth:** Bootstrap seeds + short-lived runtime tokens + recovery secrets
- **Artifacts:** Files under `~/.relay/artifacts/`, metadata in the database

The relay is intentionally **KI-less** at its core. It does not make AI
decisions; it routes tasks to registered nodes that advertise the right
capabilities. KI-capable worker nodes make decisions locally and post decision
tasks back to the relay when they need help from another agent.

## Documentation

All public Markdown docs are served live by the relay at
`/relay/v2/docs/{name}`. Available documents:

| Name | URL | Content |
|---|---|---|
| `node-readme` | `/relay/v2/docs/node-readme` | How to connect a node to the relay |
| `token-concept` | `/relay/v2/docs/token-concept` | Token and credential lifecycle |
| `setup` | `/relay/v2/docs/setup` | Server installation and configuration |
| `dashboard` | `/relay/v2/docs/dashboard` | Dashboard usage and node approval |
| `readme` | `/relay/v2/docs/readme` | This document |

Call `/relay/v2/docs` for a JSON index.

## Quick Start

```bash
cd ~/projects/ai-relay-service
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
make dev        # server with reload
make test       # run tests
make deploy     # start systemd service
```

## Core API

| Service   | Path                                  | Purpose |
|-----------|---------------------------------------|---------|
| Health    | `/health`                             | Liveness check |
| Auth      | `/relay/v2/auth/*`                    | Node registration, tokens, recovery |
| Discovery | `/relay/v2/discovery/*`                 | Heartbeats, capability registry |
| Scheduler | `/relay/v2/scheduler/*`                 | Task DAGs, stage claiming, completion |
| Presence  | `/relay/v2/presence/*`                | Online/offline state |
| Events    | `/relay/v2/events/stream?node=<id>`   | Real-time SSE event stream |

## Architecture

The relay is a thin, stateful coordination layer. It owns the registry,
heartbeat state, task DAG, and event stream, but it never runs AI inference
or domain logic itself.

```
                              ┌────────────────────────┐
                              │   AI Relay Service     │
                              │   core — port 8788     │
                              │                        │
                              │  ┌──────────────────┐  │
                              │  │  Auth / Tokens   │  │
                              │  │  (rt 7d, rs 12h) │  │
                              │  └──────────────────┘  │
                              │  ┌──────────────────┐  │
                              │  │  Discovery       │  │
                              │  │  registry +      │  │
                              │  │  heartbeats      │  │
                              │  └──────────────────┘  │
                              │  ┌──────────────────┐  │
                              │  │  Scheduler       │  │
                              │  │  task DAG +      │  │
                              │  │  stage claims    │  │
                              │  └──────────────────┘  │
                              │  ┌──────────────────┐  │
                              │  │  Events          │  │
                              │  │  SSE stream      │  │
                              │  └──────────────────┘  │
                              └────────────────────────┘
                                        ▲  ▲
           ┌────────────────────────────┘  └────────────────────────────┐
           │ heartbeat / claim / complete           register            │
           ▼                                                             ▼
  ┌────────────────────┐                                      ┌────────────────────┐
  │  Service Node      │◄──── KI-less: executes work ──────►│  Worker Node       │
  │  (storage, board)  │         directly over API          │  with local AI     │
  └────────────────────┘                                      └────────────────────┘
                                                                       │
                                                                       │ delegates
                                                                       ▼
                                                              ┌────────────────────┐
                                                              │  Local Hermes AI   │
                                                              │  decides tool/cap  │
                                                              └────────────────────┘
                                                                       │
                                                                       │ posts decision
                                                                       │ task back to relay
                                                                       ▼
                                                              ┌────────────────────┐
                                                              │  Another node      │
                                                              │  claims decision   │
                                                              │  stage             │
                                                              └────────────────────┐
                                                                                 │
                                                                                 │ executes
                                                                                 ▼
                                                                        ┌─────────────────┐
                                                                        │  Tool / Service │
                                                                        │ (image gen etc) │
                                                                        └─────────────────┘
```

### Auth flow for a new node

```
Node                              Relay
 │                                  │
 │  POST /auth/register             │
 │  (name, capabilities)             │
 │ ───────────────────────────────▶ │
 │                                  │
 │◀──────── node_id + rs ───────────│
 │                                  │
 │     admin approves via dashboard │
 │     (relay returns rt to admin)  │
 │◀──────── rt delivered ───────────│
 │                                  │
 │  loop:                           │
 │    heartbeat every 8s with rt    │
 │    claim stages with rt          │
 │    refresh rt before expiry      │
 │    refresh rs before expiry      │
 │                                  │
 │  if rt is lost:                  │
 │  POST /auth/refresh              │
 │  rs + requested=runtime_token    │
 │ ───────────────────────────────▶ │
 │                                  │
 │◀──────── new rt + new rs ────────│
```

### Key rules

- **One runtime token per node.** Refreshing it invalidates the previous one.
- **Registration secret is recovery only.** It expires after 12 hours.
- **Core is KI-less.** It routes based on capability strings; it does not choose tools.
- **KI-capable nodes decide locally.** They may post a decision task back to the
  relay so another node can execute it.

## Phase 4 Features

- **SSE Event Stream** — `GET /relay/v2/events/stream?node=<id>&types=<filter>`
  delivers real-time `node_online`, `node_offline`, `task_created`,
  `stage_claimed`, `stage_completed`, `presence_changed`, and
  `artifact_created` events. Each stream gets a unique subscriber ID, so
  reconnects from the same node do not collide. Unknown event types in the
  `types` filter return `400`.
- **External Example Nodes** — `examples/nodes/` contains standalone nodes that
  run as separate processes and talk to the core over the public v2 API.

## Optional: Storage Node

A KI-less storage service node is available in `nodes/storage-node/`. It is
**not part of the core** and runs as a separate container. It registers with
capabilities such as `storage.archive.native`, `storage.list.native`,
`storage.delete.native`, and `storage.quota.native`, downloads files from the
relay, writes them to a NAS mount, and can post cleanup decision tasks back
to the relay for AI-capable nodes to handle.

See `nodes/storage-node/README.md` for setup and
`nodes/storage-node/docker-compose.yml` for the Docker Compose deployment.

## Running the Example Nodes

Terminal 1 — create the master seed once and start the server:

```bash
cd ~/projects/ai-relay-service
source .venv/bin/activate
python -m relay_server.main admin init-master   # save the SECRET value
python -m relay_server.main server --port 8788
```

The server is now ready for bootstrap. On first install, open
`/relay/v2/dashboard/` and log in with the master seed to create the first
human admin. After that, the master seed login is disabled until recovery
mode is explicitly enabled.

Terminal 2 — start the example nodes:

```bash
cd ~/projects/ai-relay-service/examples/nodes
source ../../.venv/bin/activate
python vault_node.py --node-name "Vault Example" --base-url http://127.0.0.1:8788 &
python board_node.py --node-name "Board Example" --base-url http://127.0.0.1:8788 &
```

Terminal 3 — approve the nodes with the master secret:

```bash
cd ~/projects/ai-relay-service/examples/nodes
RELAY_MASTER_SECRET="adm_xxxxxxxxxxxx" \
  python approve_nodes.py \
  --base-url http://127.0.0.1:8788 \
  --capabilities vault,board
```

The nodes now receive runtime tokens and begin claiming matching stages. Submit
a task via the scheduler API or use `scripts/manual_node_test.py` for a fully
automated end-to-end test.

## Configuration

`~/.relay/config.yaml` (optional):

```yaml
host: 0.0.0.0
port: 8788
db_path: ~/.relay/server.db
artifacts_dir: ~/.relay/artifacts
log_level: info
```

Environment variables with the `RELAY_` prefix override YAML values.

## mDNS / Zeroconf Discovery

The relay can announce itself on the local network via mDNS so clients can find
it as `ai-relay.local` without hard-coding an IP address.

Enable it with an environment variable:

```bash
RELAY_ENABLE_MDNS=true RELAY_MDNS_HOSTNAME=ai-relay relay-server server --port 8788
```

Or in `~/.relay/config.yaml`:

```yaml
enable_mdns: true
mdns_hostname: ai-relay
```

Clients on the same subnet can then use `http://ai-relay.local:8788`.

## License

MIT
