# AI-Relay-Service v2

Eigenständiger Agent-Cluster-Server für verteilte KI-Agenten. Der Core beschränkt sich auf **Connection, Auth, Task-Verteilung und Availability-Monitoring**. Domain-Services wie Board, Vault oder Activity laufen als externe Nodes mit eigenen Capabilities.

- **Port:** 8788 (v1 läuft parallel auf 8787)
- **Framework:** FastAPI + uvicorn
- **DB:** SQLite + WAL (`~/.relay/server.db`)
- **Auth:** Bootstrap Seeds + Bearer Tokens
- **Artifacts:** Dateien unter `~/.relay/artifacts/`, Metadaten in DB

## Quick Start

```bash
cd ~/projects/ai-relay-service
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
make dev        # Server mit reload
make test       # Tests
make deploy     # systemd start
```

## Core API

| Service | Pfad |
|---------|------|
| Health | `/health` |
| Auth | `/relay/v2/auth/*` |
| Discovery | `/relay/v2/discovery/*` |
| Scheduler | `/relay/v2/scheduler/*` |
| Presence | `/relay/v2/presence/*` |
| Events | `/relay/v2/events/stream?node=<id>` |

## Phase 4 Features

- **SSE Event Stream** — `GET /relay/v2/events/stream?node=<id>&types=<filter>` delivers
  real-time `node_online`, `node_offline`, `task_created`, `stage_claimed`,
  `stage_completed`, `presence_changed`, and `artifact_created` events.
- **External Example Nodes** — `examples/nodes/` contains standalone nodes that run as
  separate processes and talk to the core over the public v2 API:
  - `vault_node.py` — advertises the `vault` capability
  - `board_node.py` — advertises the `board` capability
  - `relay_client.py` — shared HTTP/SSE client
  - `approve_nodes.py` — approves pending nodes and writes runtime tokens
- **End-to-end demo** — start the server, launch the example nodes, approve them, and
  submit a two-stage `vault` → `board` task. The nodes claim and complete their
  respective stages automatically.

## Running the Example Nodes

Terminal 1 — start the server and create the master seed once:

```bash
cd ~/projects/ai-relay-service
source .venv/bin/activate
python -m relay_server.main server --port 8788
# In another shell:
python -m relay_server.main admin init-master   # save the SECRET value
```

Terminal 2 — start the example nodes:

```bash
cd ~/projects/ai-relay-service/examples/nodes
source ../../.venv/bin/activate
python vault_node.py --node-id vault-node --base-url http://127.0.0.1:8788 &
python board_node.py --node-id board-node --base-url http://127.0.0.1:8788 &
```

Terminal 3 — approve the nodes with the master secret:

```bash
cd ~/projects/ai-relay-service/examples/nodes
RELAY_MASTER_SECRET="adm_xxxxxxxxxxxx" \
  python approve_nodes.py \
  --base-url http://127.0.0.1:8788 \
  --capabilities vault,board
```

The nodes now receive runtime tokens and begin claiming matching stages.
Submit a task via the scheduler API or use `scripts/manual_node_test.py` for a
fully automated end-to-end test.

## Architektur

```
                   ┌─────────────────────┐
                   │  AI-Relay-Service   │
                   │  (Core)             │
                   │  8788               │
                   └─────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ↓                   ↓                   ↓
   Discovery          Scheduler            Events
   Registry           Task-Queue           SSE-Stream
   Heartbeat          DAG-Stages
   Presence           Artifacts
        │                   │
        └───────────────────┘
                   │
       ┌───────────┼───────────┐
       ↓           ↓           ↓
  Board-Node  Vault-Node  Activity-Node
  capability  capability  capability
```

## Configuration

`~/.relay/config.yaml` (optional):

```yaml
host: 0.0.0.0
port: 8788
db_path: ~/.relay/server.db
artifacts_dir: ~/.relay/artifacts
log_level: info
```

Umgebungsvariablen mit `RELAY_`-Prefix überschreiben YAML-Werte.

## License

MIT
