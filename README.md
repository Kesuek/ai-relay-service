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
