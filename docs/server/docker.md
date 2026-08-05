# Docker — AI-Relay-Service (Server)

Run the relay server in a container with `docker compose`. This is the
primary deployment path for NAS owners and anyone without a Python/systemd
setup.

## Quick start (SQLite — default)

```bash
# 1. Create your environment (generate a real seed!)
cp .env.example .env
#    edit .env: set RELAY_MASTER_SEED, RELAY_SESSION_SECRET, and
#    RELAY_SESSION_COOKIE_SECURE=false (plain http on LAN)

# 2. Build & start
docker compose up -d --build

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

```bash
# 1. in .env:
RELAY_DB_TYPE=postgres
RELAY_PG_DSN=postgresql+psycopg://relay:CHANGE_ME@postgres:5432/relay
POSTGRES_USER=relay
POSTGRES_PASSWORD=CHANGE_ME
POSTGRES_DB=relay

# 2. start relay + postgres together
docker compose --profile postgres up -d --build
```

The `postgres` service is a container named `ai-relay-postgres`; the relay
reaches it at hostname `postgres` on the compose network (see `RELAY_PG_DSN`).
Its data lives in the `postgres-data` volume.

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

- `Dockerfile.relay`: multi-stage; runtime is `python:3.11-slim` with `tini` as
  PID 1 and a non-root `appuser`.
- The user is overridable via build args: `--build-arg PUID=1000 --build-arg PGID=1000`
  to match your NAS host user for bind-mounted volumes.
- `psycopg[binary]` is installed, so both SQLite and Postgres work out of the box.

## Troubleshooting

- **Healthcheck:** `docker compose ps` shows `(healthy)` once the `/health`
  endpoint responds.
- **Logs:** `docker compose logs -f relay` shows the entrypoint (seed created /
  already exists) and uvicorn output.
- **"master seed already exists":** means the DB already has a seed — your
  login is unchanged. This is normal on restart.
- **Wrong `RELAY_PG_DSN`:** the container fails fast with an init-master error;
  check the DSN host (`postgres` inside the compose network).
