# AI-Relay-Service v2

Standalone task distribution server for distributed worker nodes. The core is a
thin **coordination layer**: it connects, authenticates, distributes tasks,
and monitors availability. Domain services (Board, Vault, Storage, …) and
workers run as external nodes that register with the relay over the public v2
API and advertise their own capabilities.

> **Why "AI-Relay"?** The project started because I wanted my Mac mini to
> generate images from my Proxmox host. What grew out of it is a generic
> task distribution system — the name stuck, but the scope is much wider.
> The relay does not care whether a node runs an LLM, a shell script, or a
> database query. It just routes tasks by capability.

## Why use it?

- **You have multiple machines** — a Proxmox host, a Mac mini, a NAS, a
  cloud VM — and want them to work together without SSHing around.
- **You want to decouple requesters from workers** — submit a task, let the
  relay decide which node handles it. Add or remove nodes without touching
  the requesters.
- **You want capability-based routing** — not hardcoded IPs or queue names.
  A node says "I can do X", the relay sends it tasks for X.
- **You want trust-based auth** — token registration + admin approval.
  No shared secrets, no VPN required.
- **You want to keep it simple** — one binary, one config file, one SQLite
  database. No Kubernetes, no message broker, no service mesh.
- **You want to stay open** — AGPL-3.0, no vendor lock-in, no SaaS
  dependency. Your cluster, your rules.

- **Port:** 8788
- **Framework:** FastAPI + uvicorn
- **DB:** SQLite + WAL (`~/.relay/server.db`)
- **Auth:** Bootstrap seeds + short-lived runtime tokens + recovery secrets
- **Artifacts:** Files under `~/.relay/artifacts/`, metadata in the database

## Quick Start

```bash
git clone https://github.com/Kesuek/ai-relay-service.git
cd ai-relay-service
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
relay-server admin init-master     # save the adm_... secret
make dev                           # server with reload
```

> **Requirements:** Python 3.11+ (see `pyproject.toml`).

For the full installation, bootstrap, recovery, systemd and node setup see
**[docs/server/setup.md](docs/server/setup.md)** (server) and
**[docs/node/setup.md](docs/node/setup.md)** (nodes).

## Documentation

All public Markdown docs are served live by the relay at
`/relay/v2/docs/{name}`. Call `/relay/v2/docs` for a JSON index. The concepts
document is the central reference; everything else links back to it.

| Name | URL | File | Content | Audience |
|------|-----|------|---------|----------|
| `concepts` | `/relay/v2/docs/concepts` | [docs/concepts.md](docs/concepts.md) | Architecture, capability & token concepts, node types, self-care pattern | All |
| `server-setup` | `/relay/v2/docs/server-setup` | [docs/server/setup.md](docs/server/setup.md) | Server installation & configuration | Admin |
| `server-admin` | `/relay/v2/docs/server-admin` | [docs/server/admin.md](docs/server/admin.md) | Node management & admin API | Admin |
| `server-dashboard` | `/relay/v2/docs/server-dashboard` | [docs/server/dashboard.md](docs/server/dashboard.md) | Dashboard usage & node approval | Admin |
| `node-setup` | `/relay/v2/docs/node-setup` | [docs/node/setup.md](docs/node/setup.md) | Node setup from zero to daemon (incl. Proxmox example) | Node operator |
| `node-cli-reference` | `/relay/v2/docs/node-cli-reference` | [docs/node/cli-reference.md](docs/node/cli-reference.md) | Full `node-cli` command reference | Node operator |
| `node-capabilities` | `/relay/v2/docs/node-capabilities` | [docs/node/capabilities.md](docs/node/capabilities.md) | Capability formats & `node-cli` profiles | Node operator |
| `node-token-lifecycle` | `/relay/v2/docs/node-token-lifecycle` | [docs/node/token-lifecycle.md](docs/node/token-lifecycle.md) | Token types, refresh, recovery | Node operator |
| `reference-api` | `/relay/v2/docs/reference-api` | [docs/reference/api.md](docs/reference/api.md) | All API endpoints (Health, Auth, Discovery, Scheduler, Storage, Admin, Docs) | Developer |
| `reference-design-board` | `/relay/v2/docs/reference-design-board` | [docs/reference/design-board.md](docs/reference/design-board.md) | Message-board design | Developer |
| `reference-database-backends` | `/relay/v2/docs/reference-database-backends` | [docs/reference/database-backends.md](docs/reference/database-backends.md) | Pluggable database backends (SQLite, PostgreSQL, MariaDB) | Developer |
| `readme` | `/relay/v2/docs/readme` | [README.md](README.md) | This document | All |

Legacy short names still resolve to the current documents:

| Legacy Name | Resolves to |
|-------------|-------------|
| `setup` | `server-setup` |
| `admin-setup` | `server-admin` |
| `dashboard` | `server-dashboard` |
| `node-readme` | `node-setup` |
| `nodes-design` | `concepts` |
| `token-concept` | `concepts` |
| `token-lifecycle` | `node-token-lifecycle` |
| `capabilities` | `node-capabilities` |
| `design-board` | `reference-design-board` |
| `proxmox-worker-setup` | `node-setup` |

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
state, task DAG, and event stream, but it never runs domain logic itself.
Worker nodes decide locally and may post decision tasks back to the relay so
another node can execute them.

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
  ┌──────────────────────────────────────────────────────────────────────┐
  │  Node (one type, differentiated by capabilities)                     │
  │                                                                      │
  │  • chat.ai          → LLM chat          (worker on Mac)             │
  │  • image.gen.mflux  → image generation  (worker on Mac)             │
  │  • ssn.pages        → host dashboard    (SSN on relay host)        │
  │  • federation       → bridge relays     (federation node)          │
  └──────────────────────────────────────────────────────────────────────┘
```

See [docs/concepts.md](docs/concepts.md) for the full architecture and
self-care pattern, and [docs/node/token-lifecycle.md](docs/node/token-lifecycle.md)
for the auth flow.

### Key rules

- **One runtime token per node.** Refreshing it invalidates the previous one.
- **Registration secret is recovery only.** It expires after 12 hours.
- **Core routes by capability string.** It does not choose tools or models.

## Examples & Storage Node

- **Example nodes** in `examples/nodes/` — standalone vault and board nodes.
  See `examples/nodes/README.md` and `scripts/manual_node_test.py`.
- **Storage node** in `nodes/storage-node/` — NAS archiver, runs as a
  Docker container. See `nodes/storage-node/README.md` and
  `docs/node/setup.md`.

## Tests

```bash
source .venv/bin/activate
python -m pytest tests/ -q      # server tests in tests/, node tests in tests/nodes/
```

### Linting

```bash
ruff check .
```

### Formatting

```bash
ruff format .
```

## License

AGPL-3.0-only — see [LICENSE](LICENSE).
