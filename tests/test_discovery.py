"""Tests for discovery and presence."""

import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ["RELAY_DB_PATH"] = ""

from relay_server.config import settings
from relay_server.core.auth import generate_secret, hash_secret
from relay_server.core.db import get_conn, init_db
from relay_server.main import app


@pytest.fixture(autouse=True)
def fresh_db():
    """Use a temporary database for each test."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        settings.db_path = db_path
        settings.heartbeat_interval_seconds = 1
        settings.heartbeat_timeout_multiplier = 1
        init_db()
        yield


client = TestClient(app)


def _seed_admin() -> str:
    secret = generate_secret("adm_")
    conn = get_conn()
    conn.execute(
        "INSERT INTO admin_seeds (seed_id, seed_hash, role, created_at) VALUES (?, ?, ?, ?)",
        ("master", hash_secret(secret), "admin", "2026-01-01T00:00:00+00:00"),
    )
    conn.commit()
    conn.close()
    return secret


def _register_admin(secret: str) -> str:
    r = client.post(
        "/relay/v2/auth/register",
        json={
            "node_id": "admin-test",
            "node_name": "Admin Test",
            "bootstrap_secret": secret,
            "capabilities": [{"name": "admin", "version": "1.0.0"}],
            "role": "admin",
        },
    )
    assert r.status_code == 200
    return r.json()["token"]


def _register_worker(node_id: str, capabilities: list) -> str:
    r = client.post(
        "/relay/v2/auth/register",
        json={
            "node_id": node_id,
            "node_name": node_id.replace("-", " ").title(),
            "endpoint": "http://localhost:9001",
            "capabilities": capabilities,
            "role": "service",
        },
    )
    assert r.status_code == 200
    return r.json()["token"]


def test_heartbeat_updates_node():
    secret = _seed_admin()
    admin_token = _register_admin(secret)
    _register_worker("worker-hb", [{"name": "board", "version": "1.0.0"}])
    # Approve worker
    r = client.post(
        "/relay/v2/admin/nodes/worker-hb/approve",
        json={"role": "service", "capabilities": [{"name": "board", "version": "1.0.0"}]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    runtime = r.json()["token"]

    # Heartbeat with metadata
    r = client.post(
        "/relay/v2/discovery/heartbeat",
        headers={"Authorization": f"Bearer {runtime}"},
        json={"load": 0.5, "queue_depth": 2, "available": True},
    )
    assert r.status_code == 200

    # Node list reflects heartbeat
    r = client.get(
        "/relay/v2/discovery/nodes",
        headers={"Authorization": f"Bearer {runtime}"},
    )
    nodes = {n["node_id"]: n for n in r.json()["nodes"]}
    assert "worker-hb" in nodes
    assert nodes["worker-hb"]["load"] == 0.5
    assert nodes["worker-hb"]["queue_depth"] == 2
    assert nodes["worker-hb"]["available"] is True


def test_capability_query():
    secret = _seed_admin()
    admin_token = _register_admin(secret)
    _register_worker("worker-caps", [{"name": "vault", "version": "1.0.0"}])
    r = client.post(
        "/relay/v2/admin/nodes/worker-caps/approve",
        json={"role": "service", "capabilities": [{"name": "vault", "version": "1.0.0"}]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    runtime = r.json()["token"]

    # Heartbeat to be considered online
    client.post(
        "/relay/v2/discovery/heartbeat",
        headers={"Authorization": f"Bearer {runtime}"},
        json={},
    )

    r = client.get(
        "/relay/v2/discovery/query?capability=vault",
        headers={"Authorization": f"Bearer {runtime}"},
    )
    assert r.status_code == 200
    assert len(r.json()["nodes"]) == 1
    assert r.json()["nodes"][0]["node_id"] == "worker-caps"

    r = client.get(
        "/relay/v2/discovery/query?capability=board",
        headers={"Authorization": f"Bearer {runtime}"},
    )
    assert len(r.json()["nodes"]) == 0


def test_heartbeat_timeout_marks_offline():
    import time

    secret = _seed_admin()
    admin_token = _register_admin(secret)
    _register_worker("worker-timeout", [{"name": "vault", "version": "1.0.0"}])
    r = client.post(
        "/relay/v2/admin/nodes/worker-timeout/approve",
        json={"role": "service", "capabilities": [{"name": "vault", "version": "1.0.0"}]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    runtime = r.json()["token"]

    # One heartbeat
    client.post(
        "/relay/v2/discovery/heartbeat",
        headers={"Authorization": f"Bearer {runtime}"},
        json={},
    )

    # Wait longer than timeout
    time.sleep(2.5)

    # Directly invoke offline marking (watchdog runs on server interval)
    from relay_server.core.discovery import mark_offline_nodes

    offline = mark_offline_nodes()
    assert "worker-timeout" in offline

    r = client.get(
        "/relay/v2/discovery/nodes",
        headers={"Authorization": f"Bearer {runtime}"},
    )
    nodes = {n["node_id"]: n for n in r.json()["nodes"]}
    assert nodes["worker-timeout"]["status"] == "offline"


def test_presence_update_and_list():
    secret = _seed_admin()
    admin_token = _register_admin(secret)
    _register_worker("worker-presence", [{"name": "board", "version": "1.0.0"}])
    r = client.post(
        "/relay/v2/admin/nodes/worker-presence/approve",
        json={"role": "service", "capabilities": [{"name": "board", "version": "1.0.0"}]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    runtime = r.json()["token"]

    r = client.post(
        "/relay/v2/presence/update",
        headers={"Authorization": f"Bearer {runtime}"},
        json={
            "status": "busy",
            "mood": "focused",
            "activity": {"task_id": "t1", "name": "writing-code"},
            "progress": 42,
            "eta_seconds": 300,
        },
    )
    assert r.status_code == 200

    r = client.get(
        "/relay/v2/presence/worker-presence",
        headers={"Authorization": f"Bearer {runtime}"},
    )
    assert r.status_code == 200
    p = r.json()["presence"]
    assert p["status"] == "busy"
    assert p["mood"] == "focused"
    assert p["activity"]["name"] == "writing-code"
    assert p["progress"] == 42
    assert p["eta_seconds"] == 300

    r = client.get(
        "/relay/v2/presence/nodes",
        headers={"Authorization": f"Bearer {runtime}"},
    )
    assert len(r.json()["presence"]) == 1
