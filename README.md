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

For the full installation, bootstrap, recovery, systemd and storage-node
setup see **[docs/setup.md](docs/setup.md)**.

## Documentation

All public Markdown docs are served live by the relay at
`/relay/v2/docs/{name}`. Call `/relay/v2/docs` for a JSON index.

| Name | URL | Content | Audience |
|---|---|---|---|
| `setup` | `/relay/v2/docs/setup` | Server installation & configuration | Admin |
| `admin-setup` | `/relay/v2/docs/admin-setup` | Node management & admin API | Admin |
| `node-readme` | `/relay/v2/docs/node-readme` | How to connect a node | Node operator |
| `token-lifecycle` | `/relay/v2/docs/token-lifecycle` | Token types, refresh, recovery | Node operator |
| `capabilities` | `/relay/v2/docs/capabilities` | Capability formats & `node-cli` profiles | Node operator |
| `proxmox-worker-setup` | `/relay/v2/docs/proxmox-worker-setup` | Worker node in a Proxmox LXC | Node operator |
| `token-concept` | `/relay/v2/docs/token-concept` | Token & credential concept | Developer |
| `dashboard` | `/relay/v2/docs/dashboard` | Dashboard usage & node approval | Admin |
| `nodes-design` | `/relay/v2/docs/nodes-design` | Node architecture | Developer |
| `readme` | `/relay/v2/docs/readme` | This document | All |

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

See [docs/nodes-design.md](docs/nodes-design.md) for the full node architecture
and [docs/token-concept.md](docs/token-concept.md) for the auth flow.

### Key rules

- **One runtime token per node.** Refreshing it invalidates the previous one.
- **Registration secret is recovery only.** It expires after 12 hours.
- **Core is KI-less.** It routes by capability string; it does not choose tools.

## Examples & Storage Node

- **Example nodes** in `examples/nodes/` — standalone vault and board nodes.
  See `examples/nodes/README.md` and `scripts/manual_node_test.py`.
- **Storage node** in `nodes/storage-node/` — KI-less NAS archiver, runs as a
  Docker container. See `nodes/storage-node/README.md` and
  `docs/setup.md` §6.

## Tests

```bash
source .venv/bin/activate
python -m pytest tests/ -q      # server tests in tests/, node tests in tests/nodes/
```

## License

MIT
