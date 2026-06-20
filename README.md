# AI-Relay-Service v2

Eigenständiger Agent-Cluster-Server für verteilte KI-Agenten.

- **Port:** 8788 (v1 läuft parallel auf 8787)
- **Framework:** FastAPI + uvicorn
- **DB:** SQLite + WAL
- **Auth:** Bootstrap Seeds + Bearer Tokens

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

## Services

| Service | Pfad |
|---------|------|
| Auth | `/relay/v2/auth/*` |
| Discovery | `/relay/v2/discovery/*` |
| Scheduler | `/relay/v2/scheduler/*` |
| Board | `/relay/v2/board/*` |
| Vault | `/relay/v2/vault/*` |
| Presence | `/relay/v2/presence/*` |

## Architecture

```
Nodes → Discovery → Scheduler → Tasks → Artifacts
   ↓                      ↓
Board ← Presence ← Activity Stream
   ↓
Vault (Shared Memory)
```

## License

MIT
