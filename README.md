# AI-Relay-Service v2

Standalone agent cluster server for distributed AI agents. The core is a thin,
**KI-less** coordination layer: it connects, authenticates, distributes tasks,
and monitors availability. Domain services (Board, Vault, Storage, …) and
AI-capable workers run as external nodes that register with the relay over the
public v2 API and advertise their own capabilities.

- **Port:** 8788
- **Framework:** FastAPI + uvicorn
- **DB:** SQLite + WAL (`~/.relay/server.db`)
- **Auth:** Bootstrap seeds + short-lived runtime tokens + recovery secrets
- **Artifacts:** Files under `~/.relay/artifacts/`, metadata in the database

## Quick Start

```bash
git clone https://github.com/felix/ai-relay-service.git
cd ai-relay-service
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
relay-server admin init-master     # save the adm_... secret
make dev                           # server with reload
```

For the full installation, bootstrap, recovery, systemd and node setup see
**[docs/server/setup.md](docs/server/setup.md)** (server) and
**[docs/node/setup.md](docs/node/setup.md)** (nodes).

## Documentation

All public Markdown docs are served live by the relay at
`/relay/v2/docs/{name}`. Call `/relay/v2/docs` for a JSON index. The concepts
document is the central reference; everything else links back to it.

| Name | URL | File | Content | Audience |
|---|---|---|---|---|
| `concepts` | `/relay/v2/docs/concepts` | [docs/concepts.md](docs/concepts.md) | Architecture, capability & token concepts, node types, self-care pattern | All |
| `server-setup` | `/relay/v2/docs/server-setup` | [docs/server/setup.md](docs/server/setup.md) | Server installation & configuration | Admin |
| `server-admin` | `/relay/v2/docs/server-admin` | [docs/server/admin.md](docs/server/admin.md) | Node management & admin API | Admin |
| `server-dashboard` | `/relay/v2/docs/server-dashboard` | [docs/server/dashboard.md](docs/server/dashboard.md) | Dashboard usage & node approval | Admin |
| `node-setup` | `/relay/v2/docs/node-setup` | [docs/node/setup.md](docs/node/setup.md) | Node setup from zero to daemon (incl. Proxmox example) | Node operator |
| `node-cli-reference` | `/relay/v2/docs/node-cli-reference` | [docs/node/cli-reference.md](docs/node/cli-reference.md) | Full `node-cli` command reference | Node operator |
| `node-capabilities` | `/relay/v2/docs/node-capabilities` | [docs/node/capabilities.md](docs/node/capabilities.md) | Capability formats & `node-cli` profiles | Node operator |
| `node-token-lifecycle` | `/relay/v2/docs/node-token-lifecycle` | [docs/node/token-lifecycle.md](docs/node/token-lifecycle.md) | Token types, refresh, recovery | Node operator |
| `reference-api` | `/relay/v2/docs/reference-api` | [docs/reference/api.md](docs/reference/api.md) | All API endpoints (Health, Auth, Discovery, Scheduler, Presence, Events, Storage, Dashboard, Admin, Docs) | Developer |
| `reference-design-board` | `/relay/v2/docs/reference-design-board` | [docs/reference/design-board.md](docs/reference/design-board.md) | Message board design | Developer |
| `readme` | `/relay/v2/docs/readme` | [README.md](README.md) | This document | All |

Legacy short names (`setup`, `admin-setup`, `dashboard`, `node-readme`,
`nodes-design`, `token-concept`, `token-lifecycle`, `capabilities`,
`design-board`, `proxmox-worker-setup`) still resolve to the current files.

## Core API

| Service   | Path                                  | Purpose |
|-----------|---------------------------------------|---------|
| Health    | `/health`                             | Liveness check |
| Auth      | `/relay/v2/auth/*`                    | Node registration, tokens, recovery |
| Discovery | `/relay/v2/discovery/*`               | Heartbeats, capability registry |
| Scheduler | `/relay/v2/scheduler/*`               | Task DAGs, stage claiming, completion |
| Presence  | `/relay/v2/presence/*`                | Online/offline state |
| Events    | `/relay/v2/events/stream?node=<id>`   | Real-time SSE event stream |
| Docs      | `/relay/v2/docs`                      | Live documentation index |

## Architecture

The relay is a stateful coordination layer. It owns the registry, heartbeat
state, task DAG, and event stream, but it never runs AI inference or domain
logic itself. KI-capable worker nodes decide locally and may post decision
tasks back to the relay so another node can execute them.

```
                          ┌────────────────────────┐
                          │   AI Relay Service     │
                          │   core — port 8788     │
                          │  Auth / Discovery /     │
                          │  Scheduler / Events    │
                          └────────────────────────┘
                                    ▲  ▲
           ┌────────────────────────┘  └────────────────────────────┐
           │ heartbeat / claim / complete           register        │
           ▼                                                          ▼
  ┌────────────────────┐                                     ┌────────────────────┐
  │  Service Node      │◄─── KI-less: executes work ───────►│  Worker Node       │
  │  (storage, board)  │         directly over API          │  with local AI     │
  └────────────────────┘                                     └────────────────────┘
```

See [docs/concepts.md](docs/concepts.md) for the full node architecture and
self-care pattern, and [docs/node/token-lifecycle.md](docs/node/token-lifecycle.md)
for the auth flow.

### Key rules

- **One runtime token per node.** Refreshing it invalidates the previous one.
- **Registration secret is recovery only.** It expires after 12 hours.
- **Core is KI-less.** It routes by capability string; it does not choose tools.

## Examples & Storage Node

- **Example nodes** in `examples/nodes/` — standalone vault and board nodes.
  See `examples/nodes/README.md` and `scripts/manual_node_test.py`.
- **Storage node** in `nodes/storage-node/` — KI-less NAS archiver, runs as a
  Docker container. See `nodes/storage-node/README.md` and
  `docs/node/setup.md`.

## Tests

```bash
source .venv/bin/activate
python -m pytest tests/ -q      # server tests in tests/, node tests in tests/nodes/
```

## License

MIT
