# Database Backend Guide

> **Audience:** Developers who want to add a new database backend to the relay server.
> **Applies to:** relay-server v2.0.0+

## Overview

The relay server uses a **pluggable database abstraction** — a `Database` interface with backend-specific implementations. The active backend is selected via a single config field. Business logic (auth, scheduler, API, dashboard) never touches the database driver directly; it only calls `db.get_conn()`.

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
                                        │Database │ │Database │ │Database │
                                        └─────────┘ └─────────┘ └─────────┘
```

## Supported backends

| Backend | Config value | Driver | Status |
|---------|-------------|--------|--------|
| SQLite | `sqlite` | `sqlite3` (stdlib) | ✅ Default, fully implemented |
| PostgreSQL | `postgres` | `asyncpg` | 🚧 Stub — implementation deferred |
| MariaDB / MySQL | `mariadb` | `pymysql` | 🚧 Stub — implementation deferred |

## Adding a new backend

To add a new database backend (e.g. CockroachDB, SQL Server, PlanetScale), you need **exactly three things**:

### 1. A driver dependency

Add it to `pyproject.toml`:

```toml
[project.optional-dependencies]
cockroach = [
    "psycopg2>=2.9",  # CockroachDB speaks PostgreSQL wire protocol
]
```

### 2. A backend class

Create `src/relay_server/core/db_cockroach.py`:

```python
"""CockroachDB backend for the relay server."""

from relay_server.core.db import Database


class CockroachDatabase(Database):
    """CockroachDB backend — PostgreSQL-compatible wire protocol."""

    def __init__(self, dsn: str):
        self.dsn = dsn
        self._conn = None

    def get_conn(self):
        """Return a database connection."""
        import psycopg2
        import psycopg2.extras

        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(self.dsn)
            self._conn.autocommit = True
        return self._conn

    def init_db(self) -> None:
        """Create schema and run migrations."""
        conn = self.get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nodes (
                node_id TEXT PRIMARY KEY,
                node_name TEXT UNIQUE NOT NULL,
                ...
            )
        """)
        # ... all CREATE TABLE statements adapted to CockroachDB SQL
        # ... run_migrations() equivalent
        conn.commit()

    def close(self) -> None:
        """Release resources."""
        if self._conn and not self._conn.closed:
            self._conn.close()
```

The class must implement the `Database` protocol:

| Method | Returns | Purpose |
|--------|---------|---------|
| `get_conn()` | A connection object | Return a usable database connection. May create or pool internally. |
| `init_db()` | `None` | Create all tables, indexes, seed data, and run migrations. |
| `close()` | `None` | Release connections, close pools, clean up. |

### 3. A factory entry + config field

In `src/relay_server/core/db.py`, add to the factory:

```python
def create_database() -> Database:
    if settings.db_type == "sqlite":
        return SqliteDatabase(settings.db_path)
    elif settings.db_type == "postgres":
        return PostgresDatabase(settings.pg_dsn)
    elif settings.db_type == "mariadb":
        return MariadbDatabase(settings.mariadb_dsn)
    elif settings.db_type == "cockroach":
        return CockroachDatabase(settings.cockroach_dsn)
    else:
        raise ValueError(f"Unknown db_type: {settings.db_type}")
```

In `src/relay_server/config.py`, add the config field:

```python
cockroach_dsn: str = ""
```

### Config example

```yaml
# ~/.relay/config.yaml
db_type: cockroach
cockroach_dsn: postgresql://user:pass@host:26257/relay?sslmode=require
```

## What changes per backend

| Aspect | SQLite | PostgreSQL | MariaDB |
|--------|--------|-----------|--------|
| **Driver** | `sqlite3` (stdlib) | `asyncpg` | `pymysql` |
| **Placeholder** | `?` | `$1` | `%s` |
| **Auto-increment** | `INTEGER PRIMARY KEY AUTOINCREMENT` | `SERIAL PRIMARY KEY` | `INT AUTO_INCREMENT` |
| **Timestamp** | `strftime('%Y-%m-%dT%H:%M:%fZ', 'now')` | `NOW()` | `NOW()` |
| **Connection** | Per-call (short-lived) | Pool (long-lived) | Per-call or pool |
| **Schema** | `TEXT`, `BOOLEAN`, `REAL` | `TEXT`, `BOOLEAN`, `DOUBLE PRECISION` | `TEXT`, `BOOLEAN`, `DOUBLE` |
| **Migrations** | `PRAGMA table_info` + `ALTER TABLE` | `information_schema.columns` + `ALTER TABLE` | `information_schema.columns` + `ALTER TABLE` |

## What does NOT change

- **All business logic** — auth, users, nodes, scheduler, tasks, stages, artifacts, audit logs, presence, capabilities, routes
- **All API endpoints** — discovery, scheduling, admin, dashboard, docs
- **All tests** — they run against SQLite (in-memory or temp file) regardless of the configured backend
- **The `db.get_conn()` call pattern** — every caller uses the same import

## Testing a new backend

1. Run the existing test suite with SQLite to confirm no regressions:
   ```bash
   .venv/bin/python -m pytest tests/ -x -q
   ```

2. Start the relay with your new backend:
   ```bash
   RELAY_DB_TYPE=cockroach RELAY_COCKROACH_DSN="..." relay-server server
   ```

3. Verify the dashboard, node registration, and task scheduling work end-to-end.

## Design notes

- **No ORM.** The abstraction is deliberately thin — raw SQL per backend. An ORM would add complexity, slow down queries, and make debugging harder.
- **No shared query builder.** Each backend writes its own SQL. Shared queries (e.g. `SELECT * FROM nodes WHERE node_id = ?`) are identical across backends and live in the caller code.
- **Sync interface.** Even though `asyncpg` is async-native, the `Database` interface is sync. The PostgreSQL backend wraps async calls in `asyncio.to_thread()` or uses a sync wrapper. This keeps all callers simple.
- **Schema is per-backend.** `CREATE TABLE` syntax, data types, and migration logic differ. Each backend has its own `_schema()` and `_run_migrations()` methods.
