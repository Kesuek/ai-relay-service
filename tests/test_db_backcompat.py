"""Backward-compatibility: the existing on-disk SQLite DB must work unchanged.

T-110 hard gate. This invariant stays green for the whole SQLAlchemy Core
refactor: the on-disk SQLite database created by the legacy ``sqlite3``
code path must remain readable (and writable) after ``SqliteDatabase`` is
switched to a SQLAlchemy engine. If this test goes red, the refactor broke
the existing database and the change must be reverted.
"""

import os
import sqlite3
from pathlib import Path

os.environ.setdefault("RELAY_DB_PATH", "")
os.environ.setdefault("RELAY_SESSION_SECRET", "test-session-secret-do-not-use-in-production")

import pytest  # noqa: E402

from relay_server.config import settings  # noqa: E402
from relay_server.core.db import (  # noqa: E402
    _run_migrations,
    _schema,
    _seed_default_rbac,
    get_conn,
    init_db,
)


def _create_realistic_db(path: Path) -> None:
    """Reproduce the production schema + a few rows, exactly as db.py does."""
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    _schema(conn)
    _seed_default_rbac(conn)
    _run_migrations(conn)
    conn.execute(
        "INSERT INTO nodes (node_id, node_name, status, last_seen, registered_at) "
        "VALUES (?, ?, 'online', ?, ?)",
        ("N1234567", "test-node", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    )
    conn.commit()
    conn.close()


def test_existing_sqlite_db_readable_after_sqlalchemy(monkeypatch, tmp_path):
    """The on-disk SQLite DB created by the legacy path stays readable."""
    db = tmp_path / "server.db"
    _create_realistic_db(db)
    monkeypatch.setattr(settings, "db_path", db)

    # ``init_db`` is idempotent — it must not destroy the existing rows.
    init_db()

    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT node_id, status FROM nodes WHERE node_id = ?", ("N1234567",)
        ).fetchone()
        assert row is not None
        assert row["node_id"] == "N1234567"
        assert row["status"] == "online"

        # The RBAC seeds must survive the re-init.
        grp = conn.execute(
            "SELECT group_name FROM groups WHERE group_id = ?", ("grp_admin",)
        ).fetchone()
        assert grp is not None
        assert grp["group_name"] == "admin"
    finally:
        conn.close()


def test_existing_sqlite_db_writable_after_sqlalchemy(monkeypatch, tmp_path):
    """Writes through the new backend must keep the on-disk DB intact."""
    db = tmp_path / "server.db"
    _create_realistic_db(db)
    monkeypatch.setattr(settings, "db_path", db)
    init_db()

    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO nodes (node_id, node_name, status, last_seen, registered_at) "
            "VALUES (?, ?, 'pending', ?, ?)",
            ("N7654321", "second-node", "2026-02-02T00:00:00Z", "2026-02-02T00:00:00Z"),
        )
        conn.commit()
    finally:
        conn.close()

    # Re-open through raw sqlite3 to prove the row is on disk.
    raw = sqlite3.connect(str(db))
    raw.row_factory = sqlite3.Row
    row = raw.execute(
        "SELECT node_id, status FROM nodes WHERE node_id = ?", ("N7654321",)
    ).fetchone()
    raw.close()
    assert row is not None
    assert row["status"] == "pending"


def test_existing_sqlite_db_has_all_17_tables(monkeypatch, tmp_path):
    """All 17 tables must be present on the migrated DB."""
    db = tmp_path / "server.db"
    _create_realistic_db(db)
    monkeypatch.setattr(settings, "db_path", db)
    init_db()

    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        names = {r["name"] for r in rows}
    finally:
        conn.close()

    expected = {
        "admin_seeds", "node_seeds", "node_tokens", "users", "groups",
        "user_groups", "permissions", "group_permissions", "nodes",
        "node_capabilities", "node_routes", "presence", "tasks",
        "task_stages", "artifacts", "task_notes", "audit_logs",
    }
    assert expected.issubset(names), f"missing tables: {expected - names}"