# Docker

Container-Setups für den AI-Relay-Service. Jedes Deployment hat seinen
eigenen Unterordner.

## Verfügbare Setups

| Verzeichnis | Was | Status |
|---|---|---|
| [`server/`](server/) | Relay-Server (SQLite oder PostgreSQL) | ✅ verfügbar |

## Server

Das Server-Setup baut den Relay-Server als Container. Es unterstützt zwei
Datenbank-Backends:

- **SQLite** (Default) — DB-Datei im Named Volume `relay-data`
- **PostgreSQL** — externer Host **oder** gebündelter `postgres`-Container
  (`--profile postgres`)

Schnellstart (aus dem Repo-Root):

```bash
cp docker/server/.env.example .env   # Seed + Secrets setzen
docker compose -f docker/server/docker-compose.yml up -d --build
```

Vollständige Anleitung, DB-Wahl und Troubleshooting:
[`docs/server/docker.md`](../docs/server/docker.md)

## Node (geplant)

Ein `docker/node/`-Setup für den Worker-Node (externer Relay-Modus) ist
geplant, aber noch nicht umgesetzt.
