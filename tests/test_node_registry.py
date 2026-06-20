"""Tests for the ADR-001 node ID registry.

These tests cover unit-level generation/validation and integration-level
persistence, collision handling, and concurrent assignment safety.
"""

import os
import tempfile
import threading
from pathlib import Path

import pytest

os.environ["RELAY_DB_PATH"] = ""

from relay_server.config import settings
from relay_server.core.db import get_conn, init_db
from relay_server.core.node_registry import (
    NODE_ID_ALPHABET,
    NODE_ID_LENGTH,
    NodeRegistry,
    generate_node_id,
    normalize_node_id,
)


@pytest.fixture(autouse=True)
def fresh_db():
    """Use a temporary database for each test."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        settings.db_path = db_path
        init_db()
        yield


def test_generate_node_id_length_and_alphabet():
    node_id = generate_node_id()
    assert len(node_id) == NODE_ID_LENGTH
    assert all(ch in NODE_ID_ALPHABET for ch in node_id)


def test_node_registry_generate_unique_avoids_collision():
    registry = NodeRegistry()
    taken = {"ABCDEFGH"}
    assigned = registry.generate_unique_node_id(exists_callback=lambda c: c in taken)
    assert len(assigned) == NODE_ID_LENGTH
    assert assigned not in taken


def test_is_valid_node_id_accepts_valid_id():
    registry = NodeRegistry()
    assert registry.is_valid_node_id("ABCDEFGH") is True


def test_is_valid_node_id_accepts_lowercase_and_normalizes():
    registry = NodeRegistry()
    assert registry.is_valid_node_id("abcdefgh") is True
    assert normalize_node_id("abcdefgh") == "ABCDEFGH"


def test_is_valid_node_id_rejects_invalid_characters():
    registry = NodeRegistry()
    assert registry.is_valid_node_id("ABCDEFG1") is False  # '1' not in alphabet
    assert registry.is_valid_node_id("ABCDEFG0") is False  # '0' not in alphabet
    assert registry.is_valid_node_id("ABCDEFGO") is False  # 'O' not in alphabet


def test_is_valid_node_id_rejects_wrong_length():
    registry = NodeRegistry()
    assert registry.is_valid_node_id("ABCDEFG") is False
    assert registry.is_valid_node_id("ABCDEFGHI") is False


def test_registry_create_node_persists_metadata():
    registry = NodeRegistry()
    node_id = registry.create_node(
        node_name="Test Node",
        endpoint="http://localhost:9001",
        capabilities=[{"name": "board", "version": "1.0.0"}],
        role="worker",
        status="pending",
    )
    assert registry.is_valid_node_id(node_id)
    info = registry.lookup(node_id)
    assert info is not None
    assert info["node_name"] == "Test Node"
    assert info["endpoint"] == "http://localhost:9001"
    assert info["capabilities"] == [{"name": "board", "version": "1.0.0"}]
    assert info["status"] == "pending"
    assert info["role"] == "worker"


def test_registry_lookup_is_case_insensitive():
    registry = NodeRegistry()
    node_id = registry.create_node(
        node_name="Case Test",
        endpoint=None,
        capabilities=[],
        role="worker",
        status="approved",
    )
    assert registry.lookup(node_id.lower()) is not None
    assert registry.lookup(node_id.lower())["node_id"] == node_id


def test_registry_persists_across_registry_restarts():
    registry = NodeRegistry()
    node_id = registry.create_node(
        node_name="Persisted Node",
        endpoint=None,
        capabilities=[],
        role="worker",
        status="approved",
    )

    # Simulate a fresh process by creating a new registry instance against the
    # same on-disk database.
    new_registry = NodeRegistry()
    info = new_registry.lookup(node_id)
    assert info is not None
    assert info["node_name"] == "Persisted Node"


def test_registry_rejects_duplicate_node_name():
    from relay_server.core.node_registry import NodeNameExistsError

    registry = NodeRegistry()
    registry.create_node(
        node_name="Unique Name",
        endpoint=None,
        capabilities=[],
        role="worker",
        status="pending",
    )
    with pytest.raises(NodeNameExistsError):
        registry.create_node(
            node_name="Unique Name",
            endpoint=None,
            capabilities=[],
            role="worker",
            status="pending",
        )


def test_registry_concurrent_create_nodes_assigns_unique_ids():
    registry = NodeRegistry()
    num_threads = 32
    results = {"ids": [], "errors": []}
    lock = threading.Lock()

    def worker(idx: int):
        try:
            node_id = registry.create_node(
                node_name=f"Concurrent Node {idx}",
                endpoint=None,
                capabilities=[],
                role="worker",
                status="pending",
            )
            with lock:
                results["ids"].append(node_id)
        except Exception as exc:  # pragma: no cover - surfaced below
            with lock:
                results["errors"].append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not results["errors"], f"Concurrent registration errors: {results['errors']}"
    assert len(results["ids"]) == num_threads
    assert len(set(results["ids"])) == num_threads
    assert all(registry.is_valid_node_id(nid) for nid in results["ids"])
    assert len(registry.list_nodes()) == num_threads


def test_registry_collision_rejection_and_exhaustion():
    """With a tiny alphabet, collisions are guaranteed and rejection sampling must handle them."""
    from relay_server.core.node_registry import NodeIdExhaustedError

    registry = NodeRegistry(alphabet="AB", length=1)
    assigned = set()
    for _ in range(2):
        node_id = registry.create_node(
            node_name=f"Colliding Node {_}",
            endpoint=None,
            capabilities=[],
            role="worker",
            status="pending",
        )
        assert node_id in ("A", "B")
        assert node_id not in assigned
        assigned.add(node_id)

    # The keyspace is now exhausted; another allocation should fail cleanly.
    with pytest.raises(NodeIdExhaustedError):
        registry.create_node(
            node_name="Exhausted Node",
            endpoint=None,
            capabilities=[],
            role="worker",
            status="pending",
        )


def test_registry_generate_unique_node_id_uses_db_by_default():
    registry = NodeRegistry()
    first = registry.create_node(
        node_name="First",
        endpoint=None,
        capabilities=[],
        role="worker",
        status="pending",
    )
    # Repeated generation should never return an already-registered ID.
    for _ in range(50):
        candidate = registry.generate_unique_node_id()
        assert candidate != first
        assert not registry.is_registered(candidate)


def test_registry_list_nodes_filters_and_excludes():
    registry = NodeRegistry()
    pending_id = registry.create_node(
        node_name="Pending Node",
        endpoint=None,
        capabilities=[],
        role="worker",
        status="pending",
    )
    approved_id = registry.create_node(
        node_name="Approved Node",
        endpoint=None,
        capabilities=[],
        role="worker",
        status="approved",
    )

    all_nodes = registry.list_nodes()
    assert len(all_nodes) == 2

    pending_only = registry.list_nodes(status="pending")
    assert len(pending_only) == 1
    assert pending_only[0]["node_id"] == pending_id

    approved_only = registry.list_nodes(status="approved")
    assert len(approved_only) == 1
    assert approved_only[0]["node_id"] == approved_id

    excluded = registry.list_nodes(exclude_ids=[approved_id])
    assert len(excluded) == 1
    assert excluded[0]["node_id"] == pending_id


def test_registry_create_node_reuses_candidate_after_db_collision():
    """If the DB reports a collision, generation retries with a fresh candidate."""
    registry = NodeRegistry(alphabet="XY", length=1)
    # Manually pre-seed one ID so the first generated candidate may collide.
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO nodes (node_id, node_name, endpoint, capabilities, last_seen, "
            "registered_at, status, role) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "X",
                "Preseeded",
                None,
                "[]",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
                "pending",
                "worker",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    node_id = registry.create_node(
        node_name="Retry Node",
        endpoint=None,
        capabilities=[],
        role="worker",
        status="pending",
    )
    assert node_id == "Y"
