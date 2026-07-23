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


def test_get_capabilities_drops_stale_caps_after_replace_heartbeat():
    """T-058: capabilities that were only in the registration/approval JSON
    column but never re-confirmed by a replace_capabilities heartbeat must
    not surface in ``get_capabilities()``.

    Reproduces the original bug: a node registers with ``vault`` and
    ``image.generate.ai``, then worker-heartbeats advertising only ``vault``.
    The legacy JSON column is replaced, but the more important guarantee is
    that ``get_capabilities`` reads from the normalized ``node_capabilities``
    index (rebuilt via DELETE+INSERT on every replace), so the stale
    ``image.generate.ai`` entry disappears.
    """
    from relay_server.core.discovery import get_capabilities

    secret = _seed_admin()
    admin_id, admin_token = _register_admin(secret)

    # Register with two capabilities, approve with both.
    worker_id, _ = _register_worker(
        "Worker StaleCap",
        [
            {"name": "vault", "version": "1.0.0"},
            {"name": "image.generate.ai", "version": "1.0.0"},
        ],
    )
    r = client.post(
        f"/relay/v2/admin/nodes/{worker_id}/approve",
        json={
            "role": "service",
            "capabilities": [
                {"name": "vault", "version": "1.0.0"},
                {"name": "image.generate.ai", "version": "1.0.0"},
            ],
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    runtime = r.json()["token"]

    # First heartbeat so the node is considered online.
    client.post(
        "/relay/v2/discovery/worker-heartbeat",
        headers={"Authorization": f"Bearer {runtime}"},
        json={
            "available": True,
            "capabilities": [{"name": "vault", "version": "1.0.0"}],
        },
    )

    caps = {c["name"]: c for c in get_capabilities()}
    assert "vault" in caps
    # Stale capability must no longer be advertised.
    assert "image.generate.ai" not in caps

    # Also via the public API.
    r = client.get(
        "/relay/v2/discovery/capabilities",
        headers={"Authorization": f"Bearer {runtime}"},
    )
    assert r.status_code == 200
    names = {c["name"] for c in r.json()["capabilities"]}
    assert "vault" in names
    assert "image.generate.ai" not in names


def test_get_capabilities_fallback_to_json_when_index_empty():
    """T-058: when a node has no ``node_capabilities`` rows yet (e.g. a
    legacy node that predates the index and has not heartbeated since),
    ``get_capabilities`` falls back to the JSON column so the capability
    is not invisible until the next heartbeat arrives.
    """
    from relay_server.core.discovery import get_capabilities

    secret = _seed_admin()
    admin_id, admin_token = _register_admin(secret)
    worker_id, _ = _register_worker(
        "Worker LegacyJson", [{"name": "vault", "version": "1.0.0"}]
    )
    client.post(
        f"/relay/v2/admin/nodes/{worker_id}/approve",
        json={"role": "service", "capabilities": [{"name": "vault", "version": "1.0.0"}]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    # Pretend the index was never populated (simulates a pre-T-026 node
    # that has not heartbeated since the migration backfill ran).
    conn = get_conn()
    conn.execute("DELETE FROM node_capabilities WHERE node_id = ?", (worker_id,))
    conn.commit()
    conn.close()

    # JSON column still carries the capability → fallback must surface it.
    caps = {c["name"]: c for c in get_capabilities()}
    assert "vault" in caps


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


# ---------------------------------------------------------------------------
# T-061: mark_offline_nodes fails claimed stages of the offline node
# ---------------------------------------------------------------------------


def test_mark_offline_fails_claimed_stages():
    """When a node goes offline its claimed stages are failed (T-061)."""
    from relay_server.core.db import get_conn

    secret = _seed_admin()
    admin_id, admin_token = _register_admin(secret)
    worker_id, _ = _register_worker("Worker Claimed", [{"name": "vault", "version": "1.0.0"}])
    r = client.post(
        f"/relay/v2/admin/nodes/{worker_id}/approve",
        json={"role": "service", "capabilities": [{"name": "vault", "version": "1.0.0"}]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    runtime = r.json()["token"]

    # Create a single-stage task and claim it.
    r = client.post(
        "/relay/v2/scheduler/tasks",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"task_name": "orphan", "stages": [{"stage_name": "s1", "capability": "vault"}]},
    )
    assert r.status_code == 200
    task_id = r.json()["task"]["task_id"]
    stage_id = r.json()["stages"][0]["stage_id"]

    r = client.post(
        "/relay/v2/scheduler/claim",
        headers={"Authorization": f"Bearer {runtime}"},
        json={},
    )
    assert r.json()["claimed"] is True

    # Simulate the node going silent: backdate last_seen past the timeout.
    from datetime import datetime, timedelta, timezone

    old = (datetime.now(timezone.utc) - timedelta(seconds=400)).isoformat()
    conn = get_conn()
    conn.execute("UPDATE nodes SET last_seen = ? WHERE node_id = ?", (old, worker_id))
    conn.commit()
    conn.close()

    offline = mark_offline_nodes()
    assert worker_id in offline

    conn = get_conn()
    stage_row = conn.execute(
        "SELECT status, claimed_by FROM task_stages WHERE stage_id = ?", (stage_id,)
    ).fetchone()
    task_row = conn.execute(
        "SELECT status FROM tasks WHERE task_id = ?", (task_id,)
    ).fetchone()
    conn.close()
    assert stage_row["status"] == "failed"
    assert stage_row["claimed_by"] is None
    # Single-stage task with all stages failed → task failed.
    assert task_row["status"] == "failed"


def test_mark_offline_does_not_fail_other_nodes_stages():
    """Failing a node's claims must not touch stages claimed by another node."""
    from relay_server.core.db import get_conn

    secret = _seed_admin()
    admin_id, admin_token = _register_admin(secret)
    dying_id, _ = _register_worker("Dying", [{"name": "vault", "version": "1.0.0"}])
    healthy_id, _ = _register_worker("Healthy", [{"name": "vault", "version": "1.0.0"}])
    dying_approval = client.post(
        f"/relay/v2/admin/nodes/{dying_id}/approve",
        json={"role": "service", "capabilities": [{"name": "vault", "version": "1.0.0"}]},
        headers={"Authorization": f"Bearer {admin_token}"},
    ).json()["token"]
    healthy_approval = client.post(
        f"/relay/v2/admin/nodes/{healthy_id}/approve",
        json={"role": "service", "capabilities": [{"name": "vault", "version": "1.0.0"}]},
        headers={"Authorization": f"Bearer {admin_token}"},
    ).json()["token"]

    # Create two tasks; each node claims one.
    r = client.post(
        "/relay/v2/scheduler/tasks",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"task_name": "dying-task", "stages": [{"stage_name": "s1", "capability": "vault"}]},
    )
    dying_task_id = r.json()["task"]["task_id"]
    dying_stage_id = r.json()["stages"][0]["stage_id"]
    r = client.post(
        "/relay/v2/scheduler/tasks",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"task_name": "healthy-task", "stages": [{"stage_name": "s1", "capability": "vault"}]},
    )
    healthy_stage_id = r.json()["stages"][0]["stage_id"]

    client.post(
        "/relay/v2/scheduler/claim",
        headers={"Authorization": f"Bearer {dying_approval}"},
        json={},
    )
    client.post(
        "/relay/v2/scheduler/claim",
        headers={"Authorization": f"Bearer {healthy_approval}"},
        json={},
    )

    # Refresh the healthy node's heartbeat so it is NOT considered stale.
    client.post(
        "/relay/v2/discovery/heartbeat",
        headers={"Authorization": f"Bearer {healthy_approval}"},
        json={"available": True},
    )

    # Backdate only the dying node.
    from datetime import datetime, timedelta, timezone

    old = (datetime.now(timezone.utc) - timedelta(seconds=400)).isoformat()
    conn = get_conn()
    conn.execute("UPDATE nodes SET last_seen = ? WHERE node_id = ?", (old, dying_id))
    conn.commit()
    conn.close()

    mark_offline_nodes()

    conn = get_conn()
    dying_row = conn.execute(
        "SELECT status FROM task_stages WHERE stage_id = ?", (dying_stage_id,)
    ).fetchone()
    healthy_row = conn.execute(
        "SELECT status FROM task_stages WHERE stage_id = ?", (healthy_stage_id,)
    ).fetchone()
    conn.close()
    assert dying_row["status"] == "failed"
    # Healthy node's claim must remain untouched.
    assert healthy_row["status"] == "claimed"


def test_mark_offline_task_not_failed_when_other_stages_pending():
    """A task with another still-pending stage is not failed when one node goes offline."""
    from relay_server.core.db import get_conn

    secret = _seed_admin()
    admin_id, admin_token = _register_admin(secret)
    dying_id, _ = _register_worker("Dying Multi", [{"name": "vault", "version": "1.0.0"}])
    dying_approval = client.post(
        f"/relay/v2/admin/nodes/{dying_id}/approve",
        json={"role": "service", "capabilities": [{"name": "vault", "version": "1.0.0"}]},
        headers={"Authorization": f"Bearer {admin_token}"},
    ).json()["token"]

    # Two-stage task; only the first is claimable by the dying node.
    r = client.post(
        "/relay/v2/scheduler/tasks",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "task_name": "multi",
            "stages": [
                {"stage_name": "s1", "capability": "vault"},
                {"stage_name": "s2", "capability": "no.such.cap"},
            ],
        },
    )
    task_id = r.json()["task"]["task_id"]
    stage_id = r.json()["stages"][0]["stage_id"]

    client.post(
        "/relay/v2/scheduler/claim",
        headers={"Authorization": f"Bearer {dying_approval}"},
        json={},
    )

    from datetime import datetime, timedelta, timezone

    old = (datetime.now(timezone.utc) - timedelta(seconds=400)).isoformat()
    conn = get_conn()
    conn.execute("UPDATE nodes SET last_seen = ? WHERE node_id = ?", (old, dying_id))
    conn.commit()
    conn.close()

    mark_offline_nodes()

    conn = get_conn()
    stage_row = conn.execute(
        "SELECT status FROM task_stages WHERE stage_id = ?", (stage_id,)
    ).fetchone()
    task_row = conn.execute(
        "SELECT status FROM tasks WHERE task_id = ?", (task_id,)
    ).fetchone()
    conn.close()
    assert stage_row["status"] == "failed"
    # s2 is still pending → task must NOT be failed.
    assert task_row["status"] != "failed"
