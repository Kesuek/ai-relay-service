# Database Backend Guide

> **Audience:** Operators who want to switch the relay's database backend,
> and developers who want to add a new one.
> **Applies to:** relay-server v2.0.0+ (T-110 SQLAlchemy Core backend).

## Overview

The relay server stores all of its state — nodes, tasks, stages, tokens,
RBAC, audit logs — in a relational database. Since T-110 the database
layer is built on **SQLAlchemy Core** (not an ORM): every query goes
through a database-independent SQLAlchemy expression, so the same code
runs unchanged on SQLite, PostgreSQL, and (with a driver) MariaDB. The
active backend is selected with a single config line.

```
┌──────────────┐     get_conn() / init_db()     ┌──────────────┐
│  Relay-Code  │ ──────────────────────────→   │  Database    │
│  (auth,       │                                │  (Interface) │
│   scheduler,  │                                └──────┬───────┘
│   api, ...)   │                                       │
└──────────────┘                              ┌──────────┼──────────┐
                                               ▼          ▼          ▼
                                         ┌─────────┐ ┌─────────┐ ┌─────────┐
                                         │ SQLite  │ │Postgres │ │ MariaDB │
                                         │  (SA    │ │  (SA    │ │  (SA    │
                                         │  engine)│ │  engine)│ │  engine)│
                                         └─────────┘ └─────────┘ └─────────┘
```

Business logic (auth, scheduler, API, dashboard) never touches the
database driver directly; it calls `db.get_conn()` and receives a
SQLAlchemy `Connection`.

## Supported backends

| Backend | Config value | Driver / extra | Status |
|---------|-------------|----------------|--------|
| SQLite | `sqlite` | `sqlite3` (stdlib) | ✅ Default, fully implemented |
| PostgreSQL | `postgres` | `psycopg` (`pip install .[postgres]`) | ✅ Implemented (T-110) |
| MariaDB / MySQL | `mariadb` | `pymysql` | 🚧 Stub — implementation deferred |

## Selecting a backend

The backend is chosen in `~/.relay/config.yaml` (or the `RELAY_DB_TYPE`
env var). SQLite is the default — no configuration needed.

### SQLite (default)

```yaml
# ~/.relay/config.yaml
db_type: sqlite
db_path: ~/.relay/server.db
```

The on-disk file is the same file the legacy raw-`sqlite3` code used; the
switch to a SQLAlchemy engine is transparent and existing databases keep
working unchanged (this is the T-110 hard gate, verified by
`tests/test_db_backcompat.py`).

### PostgreSQL

```yaml
# ~/.relay/config.yaml
db_type: postgres
pg_dsn: postgresql+psycopg://user:pass@host:5432/relay
```

Install the PostgreSQL driver extra:

```bash
pip install ".[postgres]"
```

The DSN is the SQLAlchemy URL form. `pool_pre_ping` is enabled so stale
connections from the pool are detected and recycled automatically.

## What changed in T-110

Before T-110 every query was a raw `conn.execute("SELECT ... WHERE id = ?",
(id,))` string — correct only on SQLite (`?` placeholders, `sqlite3.Row`).
Switching to PostgreSQL would have required rewriting all 155 query sites
per backend. T-110 decoupled the dialect:

- **Schema** is declared once as portable `sa.Table` objects in
  `src/relay_server/core/tables.py`. `metadata.create_all(engine)` builds
  it on any backend.
- **Queries** use the `q(sql, params)` helper in `core/db.py`, which
  rewrites `?`-positional SQL into named bind parameters and lets
  SQLAlchemy render the correct placeholder per dialect (`?` on SQLite,
  `$N` on PostgreSQL, `%s` on MySQL). The legacy call shape
  (`conn.execute(q("... WHERE id = ?", (id,)))`) is preserved, so the
  155 call sites changed minimally.
- **`row["col"]` access** keeps working because a small compatibility shim
  on SQLAlchemy's `Row` forwards string subscripts to `row._mapping[col]`.
  The 373+ legacy `row["col"]` sites needed no change.
- **Migrations** are backend-aware: `PRAGMA table_info` on SQLite,
  `information_schema.columns` on PostgreSQL, centralised in
  `_column_names()` / `_table_names()`.
- **Timestamps** stay ISO-8601 **TEXT** strings (as on the existing
  SQLite database), so the on-disk DB stays byte-identical. PostgreSQL
  stores TEXT just as well; a TIMESTAMPTZ migration is a later, separate
  step if desired.

## Adding a new backend

To add a new backend (e.g. CockroachDB, SQL Server) you need **exactly
three things**:

### 1. A driver dependency

Add it as an optional extra in `pyproject.toml`:

```toml
[project.optional-dependencies]
cockroach = [
    "psycopg[binary]>=3.1",  # CockroachDB speaks the PostgreSQL wire protocol
]
```

### 2. A backend class

Create `src/relay_server/core/db_cockroach.py`, mirroring
`db_postgres.py`. Because the schema and migrations are already portable,
the class is tiny — a SQLAlchemy engine + the shared `init_db`:

```python
"""CockroachDB backend for the relay server."""
import sqlalchemy as sa
from relay_server.core import tables
from relay_server.core.db import Database, _run_migrations, _seed_default_rbac


class CockroachDatabase(Database):
    def __init__(self, dsn: str):
        self._dsn = dsn
        self._engine = None

    def _get_engine(self):
        if self._engine is None:
            self._engine = sa.create_engine(self._dsn, pool_pre_ping=True, future=True)
        return self._engine

    def get_conn(self):
        return self._get_engine().connect()

    def init_db(self):
        with self._get_engine().begin() as conn:
            tables.metadata.create_all(conn)
            _seed_default_rbac(conn)
            _run_migrations(conn)

    def close(self):
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
```

### 3. A factory entry + config field

In `create_database()` (`core/db.py`):

```python
elif db_type == "cockroach":
    from relay_server.core.db_cockroach import CockroachDatabase
    return CockroachDatabase(settings.cockroach_dsn)
```

In `config.py`:

```python
cockroach_dsn: str = ""
```

### Config example

```yaml
db_type: cockroach
cockroach_dsn: postgresql+psycopg://user:pass@host:26257/relay?sslmode=require
```

## What does NOT change

- **All business logic** — auth, users, nodes, scheduler, tasks, stages,
  artifacts, audit logs, presence, capabilities, routes.
- **All API endpoints** — discovery, scheduling, admin, dashboard, docs.
- **All tests** — they run against SQLite (temp file) regardless of the
  configured backend, plus the `test_db_backcompat.py` invariant guarding
  the existing on-disk database.
- **The `db.get_conn()` / `q()` call pattern** — every caller uses the
  same imports.

## Testing a new backend

1. Run the existing suite with SQLite to confirm no regressions:
   ```bash
   .venv/bin/python -m pytest tests/ -x -q
   ```
2. Run the backcompat invariant to confirm the existing SQLite DB stays
   intact:
   ```bash
   .venv/bin/python -m pytest tests/test_db_backcompat.py -x -q
   ```
3. Start the relay with the new backend and verify registration,
   heartbeat, scheduling, and the dashboard end-to-end.

## Design notes

- **No ORM.** SQLAlchemy Core (expressions + `text()`), not the ORM. The
  relay keeps full control of the SQL while gaining dialect portability.
- **`q()` helper, not a query builder.** The legacy `?`-SQL call shape is
  preserved; `q()` only rewrites placeholders and binds params. New code
  may use full `sa.select()` / `sa.insert()` constructs directly.
- **Sync interface.** The `Database` interface is sync. SQLAlchemy's
  engine + connection pool is sync-native; the async server runs DB calls
  in the threadpool via Starlette/FastAPI's standard sync route support.
- **Schema is shared.** One `tables.metadata` drives `create_all` on every
  backend. The legacy raw-DDL `_schema()` is kept for the SQLite path so
  existing databases initialise byte-identically; new backends use
  `metadata.create_all`.
- **SQLite stays default.** PostgreSQL is opt-in. There is no migration
  step for existing deployments — the SQLite file is unchanged.