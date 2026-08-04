"""Tests for the portable SQLAlchemy Table definitions (T-110)."""

import sqlalchemy as sa

from relay_server.core import tables


def test_all_17_tables_defined():
    names = set(tables.metadata.tables.keys())
    expected = {
        "admin_seeds", "node_seeds", "node_tokens", "users", "groups",
        "user_groups", "permissions", "group_permissions", "nodes",
        "node_capabilities", "node_routes", "presence", "tasks",
        "task_stages", "artifacts", "task_notes", "audit_logs",
    }
    assert expected.issubset(names), f"missing: {expected - names}"


def test_metadata_is_sa_metadata():
    assert isinstance(tables.metadata, sa.MetaData)


def test_nodes_table_columns_match_legacy_schema():
    cols = {c.name for c in tables.nodes.columns}
    expected = {
        "node_id", "node_name", "endpoint", "capabilities", "load",
        "queue_depth", "available", "last_seen", "registered_at",
        "status", "role", "first_heartbeat_seen",
        "registration_secret_hash", "registration_secret_expires_at",
        "description", "consecutive_high_load",
    }
    assert expected.issubset(cols), f"missing cols: {expected - cols}"


def test_node_tokens_has_lookup_hash():
    cols = {c.name for c in tables.node_tokens.columns}
    assert "token_lookup_hash" in cols


def test_task_notes_id_autoincrement():
    id_col = tables.task_notes.c.id
    assert id_col.autoincrement is True


def test_indexes_present():
    # ``sa.Index`` objects are attached to individual tables via the
    # metadata; collect them from every table.
    index_names = set()
    for table in tables.metadata.sorted_tables:
        for idx in table.indexes:
            if idx.name:
                index_names.add(idx.name)
    expected = {
        "idx_node_capabilities_name", "idx_node_capabilities_name_type",
        "idx_task_notes_task_id", "idx_audit_logs_created",
        "idx_audit_logs_actor", "idx_nodes_status", "idx_nodes_capabilities",
        "idx_tasks_status", "idx_tasks_priority", "idx_task_stages_task",
        "idx_task_stages_status", "idx_task_stages_capability",
        "idx_artifacts_task", "idx_presence_status", "idx_node_tokens_lookup",
    }
    assert expected.issubset(index_names), f"missing: {expected - index_names}"


def test_metadata_creates_schema_on_in_memory_sqlite():
    """Smoke test: ``create_all`` runs cleanly on a fresh SQLite engine."""
    engine = sa.create_engine("sqlite://", future=True)
    tables.metadata.create_all(engine)
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        ).fetchall()
        names = {r[0] for r in rows}
    expected = {
        "admin_seeds", "node_seeds", "node_tokens", "users", "groups",
        "user_groups", "permissions", "group_permissions", "nodes",
        "node_capabilities", "node_routes", "presence", "tasks",
        "task_stages", "artifacts", "task_notes", "audit_logs",
    }
    assert expected.issubset(names)