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

## Special Nodes (noch nicht final)

Die spezialisierten Nodes (z.B. Storage-Node, SSN) sind **noch nicht
containerisiert** — das Konzept wird aktuell überarbeitet, kein special node
ist derzeit wirklich fertig. Sobald die Richtung steht, bekommt jeder
finale special node hier einen eigenen Unterordner (`docker/<node>/`).

> Hinweis: Das ältere `nodes/storage-node/`-Docker-Setup ist **veraltet** und
> wird nicht weitergepflegt.
