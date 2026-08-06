# Docker

Container setups for the AI-Relay-Service. Each deployment lives in its own
subdirectory.

## Available setups

| Directory | What | Status |
|---|---|---|
| [`server/`](server/) | Relay server (SQLite or PostgreSQL) | ✅ available |

## Server

The server setup builds the relay server as a container. It supports two
database backends:

- **SQLite** (default) — DB file in the named volume `relay-data`
- **PostgreSQL** — external host **or** bundled `postgres` container
  (`--profile postgres`)

Quick start (from the repo root):

```bash
cp docker/server/.env.example .env   # set seed + secrets
docker compose -f docker/server/docker-compose.yml up -d --build
```

Full guide, DB choice, and troubleshooting:
[`docs/server/docker.md`](../docs/server/docker.md)

## Special nodes (not final yet)

The specialized nodes (e.g. storage node, SSN) are **not containerized yet** —
the concept is currently being reworked, and no special node is production-ready
at this point. Once the direction is settled, each final special node gets its
own subdirectory here (`docker/<node>/`).

> Note: The older `nodes/storage-node/` Docker setup is **deprecated** and no
> longer maintained.
