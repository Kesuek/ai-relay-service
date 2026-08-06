# Docker — AI-Relay-Service (Server)

Run the relay server in a container with `docker compose`. This is the
primary deployment path for NAS owners and anyone without a Python/systemd
setup.

## Quick start (SQLite — default)

```bash
# 1. Create your environment (generate a real seed!)
cp docker/.env.example .env
#    edit .env: set RELAY_MASTER_SEED, RELAY_SESSION_SECRET, and
#    RELAY_SESSION_COOKIE_SECURE=false (plain http on LAN)

# 2. Build & start (from the repo root)
docker compose -f docker/docker-compose.yml up -d --build

# 3. Open the dashboard
#    http://<host>:8788
#    log in with your master seed (mode: seed)
```

SQLite is the default backend. The database file, artifacts, and config live
in the named volume `relay-data`, so they survive `docker compose down` and
rebuilds. Only `docker compose down -v` removes them.

## Choosing the database backend

Two backends are supported. **MariaDB is not yet implemented** and is not
offered.

| Backend | How to enable | When to pick it |
|---|---|---|
| SQLite (default) | nothing to do | Single relay, no external DB, simplest |
| PostgreSQL | `--profile postgres` + env | Shared / larger / multi-process use |

### PostgreSQL

PostgreSQL can be used in two ways:

- **External database on another host** (existing Postgres server, another
  machine, a managed DB). No `postgres` service is needed — just point
  `RELAY_PG_DSN` at it and start the relay normally.
- **Bundled `postgres` container** (via the `postgres` profile) for a
  self-contained setup.

In both cases the relay only needs `RELAY_DB_TYPE=postgres` and a valid
`RELAY_PG_DSN`. The `POSTGRES_*` variables are **only** used to configure the
bundled `postgres` container — they are irrelevant for an external database.

#### Option A — external Postgres on another host

```dotenv
RELAY_DB_TYPE=postgres
RELAY_PG_DSN=postgresql+psycopg://relay:MEIN_PASSWORT@192.168.1.50:5432/relay
```

Start the relay alone (no `--profile postgres`):

```bash
docker compose -f docker/docker-compose.yml up -d --build
```

The DSN host can be any reachable address: an IP, a hostname, or a Tailscale
name. The relay container must be able to reach it (network/firewall).

#### Option B — bundled `postgres` container

```dotenv
RELAY_DB_TYPE=postgres
RELAY_PG_DSN=postgresql+psycopg://relay:MEIN_PASSWORT@postgres:5432/relay
POSTGRES_USER=relay
POSTGRES_PASSWORD=MEIN_PASSWORT
POSTGRES_DB=relay
```

Start relay + postgres together:

```bash
docker compose -f docker/docker-compose.yml --profile postgres up -d --build
```

The `postgres` service is a container named `ai-relay-postgres`; the relay
reaches it at hostname `postgres` on the compose network. Its data lives in
the `postgres-data` volume.

#### Postgres pitfalls

1. **DSN dialect must be `postgresql+psycopg://`.** `postgres://` alone is not
   enough — the server uses the psycopg dialect explicitly.
2. **In Option B the DSN host is `postgres`, not `localhost`.** The relay runs
   in its own container on the same compose network; `localhost` would point at
   the relay container itself, not the database. In Option A the host is your
   external server's address.
3. **In Option B, `RELAY_PG_DSN` and `POSTGRES_PASSWORD` must carry the same
   password.** A mismatch fails fast at the entrypoint (visible in
   `docker compose logs`), not as a silent half-failure. In Option A only the
   DSN matters — the password lives in the DSN itself.

## Master admin seed

The master seed is **stored (hashed) in the database**. Set it in `.env` as
`RELAY_MASTER_SEED`; the container entrypoint applies it on first start. If it
is unset, a random seed is generated and printed to the container log on the
first run.

**Losing the database volume loses the seed** (and all admin sessions). Keep
the `relay-data` volume (and `postgres-data`) intact — do not run
`docker compose down -v` casually.

## Environment reference

| Variable | Default | Purpose |
|---|---|---|
| `RELAY_MASTER_SEED` | *(random)* | Deterministic master admin seed |
| `RELAY_DB_TYPE` | `sqlite` | `sqlite` or `postgres` |
| `RELAY_PG_DSN` | *(empty)* | Postgres DSN, e.g. `postgresql+psycopg://...` |
| `RELAY_SESSION_SECRET` | *(empty)* | Signs dashboard session cookies (≥32 chars) |
| `RELAY_SESSION_COOKIE_SECURE` | `true` | `false` over plain http on LAN |
| `POSTGRES_USER` / `_PASSWORD` / `_DB` | `relay` | Credentials for the `postgres` service |

## Image & user

- `docker/Dockerfile.relay`: multi-stage; runtime is `python:3.11-slim` with
  `tini` as PID 1 and a non-root `appuser`.
- The user is overridable via build args: `--build-arg PUID=1000 --build-arg PGID=1000`
  to match your NAS host user for bind-mounted volumes.
- `psycopg[binary]` is installed, so both SQLite and Postgres work out of the box.

All Docker files live in the `docker/` subdirectory. Build from the repo root
with `-f docker/docker-compose.yml` (the build context is the repo root, so
`COPY src` / `COPY nodes` resolve correctly).

## Troubleshooting

- **Healthcheck:** `docker compose -f docker/docker-compose.yml ps` shows
  `(healthy)` once the `/health` endpoint responds.
- **Logs:** `docker compose -f docker/docker-compose.yml logs -f relay` shows
  the entrypoint (seed created / already exists) and uvicorn output.
- **"master seed already exists":** means the DB already has a seed — your
  login is unchanged. This is normal on restart.
- **Wrong `RELAY_PG_DSN`:** the container fails fast with an init-master error;
  check the DSN host (`postgres` inside the compose network).
