# (AI-)Relay-Service

**One relay. Unlimited worker nodes.**
Capability-based task routing for distributed workers.

Nodes are self-describing. They register, advertise what they can do, and the
relay routes tasks to them — no static configuration, no central registry of
services, no Kubernetes.

```
             ┌─────────────────────┐
             │  Task / Request      │
             └──────────┬──────────┘
                        │
                        ▼
             ┌─────────────────────┐
             │   AI Relay Service  │
             │   routes by         │
             │   capability string │
             └───────┬──┬──┬───────┘
                     │  │  │
           ┌─────────┘  │  └─────────┐
           ▼             ▼            ▼
     ┌──────────┐  ┌──────────┐  ┌──────────┐
     │  Mac     │  │  Linux   │  │  NAS     │
     │  MLX     │  │  Ollama  │  │  Archive │
     │  images  │  │  chat    │  │  storage │
     └──────────┘  └──────────┘  └──────────┘
```

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

## How it works

1. **A node registers** with the relay and gets a token.
2. **An admin approves** the node — trust is established.
3. **The node heartbeats** its capabilities: `chat.ai`, `image.gen.mflux`,
   `storage.archive.native`, `printer.print` — whatever it can do.
4. **Tasks arrive** with a capability name. The relay finds a matching node
   and routes the task.
5. **The node claims, executes, and completes** — the result goes back
   through the relay.

**Nodes are self-describing.** The relay knows nothing about what a capability
does. It only matches names. Add a new node type by writing a YAML profile
and a handler script — no relay code changes needed.

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

## What you can connect

| Node | Capability | What it does |
|------|-----------|-------------|
| Mac mini | `image.gen.mflux` | Generate images via FLUX |
| Linux server | `chat.ai` | Run Ollama or vLLM |
| NAS | `storage.archive.native` | Archive files |
| Raspberry Pi | `switch.toggle` | Toggle smart-home switches |
| Any machine | `printer.print` | Print documents |
| Any machine | `web.ai` | Search and summarise |

One machine can run multiple nodes. One capability can run on multiple
machines for load balancing and failover.

## Documentation

All public Markdown docs are served live by the relay at
`/relay/v2/docs/{name}`. Call `/relay/v2/docs` for a JSON index.

| Name | Content | Audience |
|------|---------|----------|
| `concepts` | Architecture, capabilities, tokens, self-care pattern | All |
| `server-setup` | Server installation & configuration | Admin |
| `server-admin` | Node management & admin API | Admin |
| `server-dashboard` | Dashboard usage & node approval | Admin |
| `node-setup` | Node setup from zero to daemon | Node operator |
| `node-cli-reference` | Full `node-cli` command reference | Node operator |
| `node-capabilities` | Capability formats & profiles | Node operator |
| `node-token-lifecycle` | Token types, refresh, recovery | Node operator |
| `reference-api` | All API endpoints | Developer |
| `reference-design-board` | Message-board design | Developer |
| `reference-database-backends` | Pluggable database backends | Developer |

## Core API

| Service | Path | Purpose |
|---------|------|---------|
| Health | `/health` | Liveness check |
| Auth | `/relay/v2/auth/*` | Node registration, tokens, recovery |
| Discovery | `/relay/v2/discovery/*` | Heartbeats, capability registry |
| Scheduler | `/relay/v2/scheduler/*` | Task DAGs, stage claiming, completion |
| Events | `/relay/v2/events/stream?node=<id>` | Real-time SSE event stream |
| Docs | `/relay/v2/docs` | Live documentation index |

## Key rules

- **One runtime token per node.** Refreshing it invalidates the previous one.
- **Registration secret is recovery only.** It expires after 12 hours.
- **The core routes tasks by capability string.** It does not choose tools or models.

## Tests

```bash
source .venv/bin/activate
python -m pytest tests/ -q
```

## License

AGPL-3.0-only — see [LICENSE](LICENSE).
