"""Tests for discovery and presence."""

import asyncio
import json
import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ["RELAY_DB_PATH"] = ""

from relay_server.config import settings
from relay_server.core.auth import generate_secret, hash_secret
from relay_server.core.db import get_conn, init_db
from relay_server.core.discovery import mark_offline_nodes
from relay_server.core.events import event_bus
from relay_server.main import app


@pytest.fixture(autouse=True)
def fresh_db():
    """Use a temporary database for each test and reset the event bus."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        settings.db_path = db_path
        settings.heartbeat_interval_seconds = 1
        settings.heartbeat_timeout_multiplier = 1
        init_db()
        event_bus.clear()
        yield
        event_bus.clear()


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


def _register_admin(secret: str) -> tuple[str, str]:
    r = client.post(
        "/relay/v2/auth/register-admin",
        json={
            "node_name": "Admin Test",
            "bootstrap_secret": secret,
            "capabilities": [{"name": "admin", "version": "1.0.0"}],
        },
    )
    assert r.status_code == 200
    body = r.json()
    return body["node_id"], body["token"]


def _register_worker(name: str, capabilities: list) -> tuple[str, str]:
    r = client.post(
        "/relay/v2/auth/register",
        json={
            "node_name": name,
            "endpoint": "http://localhost:9001",
            "capabilities": capabilities,
            "role": "service",
        },
    )
    assert r.status_code == 200
    body = r.json()
    return body["node_id"], body["token"]


def test_heartbeat_updates_node():
    secret = _seed_admin()
    admin_id, admin_token = _register_admin(secret)
    worker_id, _ = _register_worker("Worker Hb", [{"name": "board", "version": "1.0.0"}])
    # Approve worker
    r = client.post(
        f"/relay/v2/admin/nodes/{worker_id}/approve",
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
    assert worker_id in nodes
    assert nodes[worker_id]["load"] == 0.5
    assert nodes[worker_id]["queue_depth"] == 2
    assert nodes[worker_id]["available"] is True


def test_capability_query():
    secret = _seed_admin()
    admin_id, admin_token = _register_admin(secret)
    worker_id, _ = _register_worker("Worker Caps", [{"name": "vault", "version": "1.0.0"}])
    r = client.post(
        f"/relay/v2/admin/nodes/{worker_id}/approve",
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
    assert r.json()["nodes"][0]["node_id"] == worker_id

    r = client.get(
        "/relay/v2/discovery/query?capability=board",
        headers={"Authorization": f"Bearer {runtime}"},
    )
    assert len(r.json()["nodes"]) == 0


def test_heartbeat_timeout_marks_offline():
    import time

    secret = _seed_admin()
    admin_id, admin_token = _register_admin(secret)
    worker_id, _ = _register_worker("Worker Timeout", [{"name": "vault", "version": "1.0.0"}])
    r = client.post(
        f"/relay/v2/admin/nodes/{worker_id}/approve",
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
    assert worker_id in offline

    r = client.get(
        "/relay/v2/discovery/nodes",
        headers={"Authorization": f"Bearer {runtime}"},
    )
    nodes = {n["node_id"]: n for n in r.json()["nodes"]}
    assert nodes[worker_id]["status"] == "offline"


def test_presence_update_and_list():
    secret = _seed_admin()
    admin_id, admin_token = _register_admin(secret)
    worker_id, _ = _register_worker("Worker Presence", [{"name": "board", "version": "1.0.0"}])
    r = client.post(
        f"/relay/v2/admin/nodes/{worker_id}/approve",
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
        f"/relay/v2/presence/{worker_id}",
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


def test_heartbeat_rejects_invalid_payload():
    secret = _seed_admin()
    admin_id, admin_token = _register_admin(secret)
    worker_id, _ = _register_worker("Worker Invalid Hb", [{"name": "board", "version": "1.0.0"}])
    r = client.post(
        f"/relay/v2/admin/nodes/{worker_id}/approve",
        json={"role": "service", "capabilities": [{"name": "board", "version": "1.0.0"}]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    runtime = r.json()["token"]

    r = client.post(
        "/relay/v2/discovery/heartbeat",
        headers={"Authorization": f"Bearer {runtime}"},
        json={"load": 2.0, "queue_depth": -1},
    )
    assert r.status_code == 422

    r = client.post(
        "/relay/v2/discovery/heartbeat",
        headers={"Authorization": f"Bearer {runtime}"},
        json={"endpoint": "x" * 3000},
    )
    assert r.status_code == 422


def test_presence_update_rejects_invalid_payload():
    secret = _seed_admin()
    admin_id, admin_token = _register_admin(secret)
    worker_id, _ = _register_worker(
        "Worker Invalid Presence", [{"name": "board", "version": "1.0.0"}]
    )
    r = client.post(
        f"/relay/v2/admin/nodes/{worker_id}/approve",
        json={"role": "service", "capabilities": [{"name": "board", "version": "1.0.0"}]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    runtime = r.json()["token"]

    r = client.post(
        "/relay/v2/presence/update",
        headers={"Authorization": f"Bearer {runtime}"},
        json={"progress": 150, "eta_seconds": -10},
    )
    assert r.status_code == 422

    r = client.post(
        "/relay/v2/presence/update",
        headers={"Authorization": f"Bearer {runtime}"},
        json={"status": "x" * 100},
    )
    assert r.status_code == 422

    r = client.post(
        "/relay/v2/presence/update",
        headers={"Authorization": f"Bearer {runtime}"},
        json={"mood": "x" * 100},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_node_online_emitted_on_first_heartbeat():
    secret = _seed_admin()
    admin_id, admin_token = _register_admin(secret)
    worker_id, _ = _register_worker("Worker Online", [{"name": "board", "version": "1.0.0"}])
    r = client.post(
        f"/relay/v2/admin/nodes/{worker_id}/approve",
        json={"role": "service", "capabilities": [{"name": "board", "version": "1.0.0"}]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    runtime = r.json()["token"]

    received: list[dict] = []

    async def consumer():
        async for message in event_bus.subscribe(event_types={"node_online"}):
            data = json.loads(message.split("data: ", 1)[1].split("\n\n", 1)[0])
            received.append(data)
            break

    task = asyncio.create_task(consumer())
    for _ in range(100):
        if event_bus.subscriber_count() == 1:
            break
        await asyncio.sleep(0.01)

    r = client.post(
        "/relay/v2/discovery/heartbeat",
        headers={"Authorization": f"Bearer {runtime}"},
        json={"available": True},
    )
    assert r.status_code == 200

    await asyncio.wait_for(task, timeout=2.0)
    assert len(received) == 1
    assert received[0]["type"] == "node_online"
    assert received[0]["payload"]["node_id"] == worker_id


@pytest.mark.asyncio
async def test_presence_no_event_on_no_op_update():
    secret = _seed_admin()
    admin_id, admin_token = _register_admin(secret)
    worker_id, _ = _register_worker("Worker Presence Noop", [{"name": "board", "version": "1.0.0"}])
    r = client.post(
        f"/relay/v2/admin/nodes/{worker_id}/approve",
        json={"role": "service", "capabilities": [{"name": "board", "version": "1.0.0"}]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    runtime = r.json()["token"]

    # Establish an initial presence value.
    r = client.post(
        "/relay/v2/presence/update",
        headers={"Authorization": f"Bearer {runtime}"},
        json={"status": "busy"},
    )
    assert r.status_code == 200

    received: list[dict] = []

    async def consumer():
        async for message in event_bus.subscribe(event_types={"presence_changed"}):
            data = json.loads(message.split("data: ", 1)[1].split("\n\n", 1)[0])
            received.append(data)
            if len(received) == 1:
                break

    task = asyncio.create_task(consumer())
    for _ in range(100):
        if event_bus.subscriber_count() == 1:
            break
        await asyncio.sleep(0.01)

    # Send an identical update; it should not emit presence_changed.
    r = client.post(
        "/relay/v2/presence/update",
        headers={"Authorization": f"Bearer {runtime}"},
        json={"status": "busy"},
    )
    assert r.status_code == 200

    # Give any erroneously emitted event a moment to arrive.
    await asyncio.sleep(0.2)
    assert len(received) == 0
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def test_stale_nodes_marked_offline():
    """Nodes with no recent heartbeat are marked offline."""
    secret = _seed_admin()
    admin_id, admin_token = _register_admin(secret)
    worker_id, _ = _register_worker("Stale Worker", [{"name": "board", "version": "1.0.0"}])
    r = client.post(
        f"/relay/v2/admin/nodes/{worker_id}/approve",
        json={"role": "service", "capabilities": [{"name": "board", "version": "1.0.0"}]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    runtime = r.json()["token"]

    # First heartbeat makes the node online.
    r = client.post(
        "/relay/v2/discovery/heartbeat",
        headers={"Authorization": f"Bearer {runtime}"},
        json={"available": True},
    )
    assert r.status_code == 200

    r = client.get(
        "/relay/v2/admin/nodes",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    worker = next(n for n in r.json()["nodes"] if n["node_id"] == worker_id)
    assert worker["status"] in ("online", "approved")

    # Simulate old heartbeat by moving last_seen back in time.
    from datetime import datetime, timedelta, timezone

    from relay_server.core.db import get_conn
    old = (datetime.now(timezone.utc) - timedelta(seconds=400)).isoformat()
    conn = get_conn()
    conn.execute("UPDATE nodes SET last_seen = ? WHERE node_id = ?", (old, worker_id))
    conn.commit()
    conn.close()


    updated = mark_offline_nodes()
    assert worker_id in updated

    r = client.get(
        "/relay/v2/admin/nodes",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    worker = next(n for n in r.json()["nodes"] if n["node_id"] == worker_id)
    assert worker["status"] == "offline"
    assert worker["status"] == "offline"


def test_register_without_capabilities_then_set_via_heartbeat():
    """Node registered with no capabilities can advertise them via heartbeat (T-047).

    The worker registers with an empty capabilities list (the models default
    to ``default_factory=list``). After admin approval it sends a
    ``replace_capabilities`` heartbeat advertising ``chat.ai``; the server
    must persist and index that capability so the scheduler can find it.
    """
    from relay_server.core.db import get_node_capability_names, nodes_with_capability

    secret = _seed_admin()
    admin_id, admin_token = _register_admin(secret)

    # Register worker WITHOUT capabilities.
    worker_id, _ = _register_worker("Worker NoCaps", [])
    assert worker_id

    # The pending node must have no capabilities recorded yet.
    conn = get_conn()
    row = conn.execute(
        "SELECT capabilities FROM nodes WHERE node_id = ?", (worker_id,)
    ).fetchone()
    conn.close()
    assert row["capabilities"] in (None, "", "[]", "null")

    # Approve the node without overriding capabilities (body.capabilities=None).
    r = client.post(
        f"/relay/v2/admin/nodes/{worker_id}/approve",
        json={"role": "service"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    runtime = r.json()["token"]

    # Heartbeat with replace_capabilities advertising the real capability.
    r = client.post(
        "/relay/v2/discovery/heartbeat",
        headers={"Authorization": f"Bearer {runtime}"},
        json={
            "available": True,
            "capabilities": [{"name": "chat.ai", "version": "1.0.0"}],
        },
    )
    assert r.status_code == 200

    # The capability must be persisted on the node row…
    conn = get_conn()
    row = conn.execute(
        "SELECT capabilities FROM nodes WHERE node_id = ?", (worker_id,)
    ).fetchone()
    conn.close()
    caps = json.loads(row["capabilities"]) if row["capabilities"] else []
    assert any(c.get("name") == "chat.ai" for c in caps)

    # …and mirrored into the normalized node_capabilities index.
    assert "chat.ai" in get_node_capability_names(worker_id)
    assert worker_id in nodes_with_capability("chat.ai")


def test_heartbeat_with_empty_replace_capabilities_clears_index():
    """A replace_capabilities heartbeat with [] must clear the index (T-047).

    Guards against stale rows in ``node_capabilities`` when a node drops
    its last capability. ``sync_node_capabilities`` must accept an empty
    list without raising.
    """
    from relay_server.core.db import get_node_capability_names

    secret = _seed_admin()
    admin_id, admin_token = _register_admin(secret)
    worker_id, _ = _register_worker("Worker DropCap", [{"name": "temp.cap", "version": "1.0.0"}])
    r = client.post(
        f"/relay/v2/admin/nodes/{worker_id}/approve",
        json={"role": "service", "capabilities": [{"name": "temp.cap", "version": "1.0.0"}]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    runtime = r.json()["token"]

    # Advertise then drop via worker-heartbeat (replace mode).
    client.post(
        "/relay/v2/discovery/worker-heartbeat",
        headers={"Authorization": f"Bearer {runtime}"},
        json={"available": True, "capabilities": [{"name": "temp.cap", "version": "1.0.0"}]},
    )
    assert get_node_capability_names(worker_id) == ["temp.cap"]

    client.post(
        "/relay/v2/discovery/worker-heartbeat",
        headers={"Authorization": f"Bearer {runtime}"},
        json={"available": True, "capabilities": []},
    )
    assert get_node_capability_names(worker_id) == []
