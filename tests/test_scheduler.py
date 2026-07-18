"""Tests for scheduler task lifecycle."""

import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Optional

import pytest
from fastapi.testclient import TestClient

os.environ["RELAY_DB_PATH"] = ""
os.environ["RELAY_SESSION_SECRET"] = "test-session-secret-do-not-use-in-production"

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
        settings.session_secret = "test-session-secret-do-not-use-in-production"
        settings.heartbeat_interval_seconds = 10
        settings.heartbeat_timeout_multiplier = 2
        settings.claim_ttl_seconds = 60
        # Reset cached pepper so each test re-evaluates session_secret.
        import relay_server.core.auth as auth_mod

        auth_mod._TOKEN_PEPPER = None
        init_db()
        yield
        auth_mod._TOKEN_PEPPER = None


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


def _admin_token(secret: str) -> str:
    r = client.post(
        "/relay/v2/auth/register-admin",
        json={
            "node_name": "Admin Test",
            "bootstrap_secret": secret,
            "capabilities": [{"name": "admin", "version": "1.0.0"}],
        },
    )
    assert r.status_code == 200
    return r.json()["token"]


def _register(
    secret: str,
    node_name: str,
    caps: list,
    role: str = "service",
    admin_token: Optional[str] = None,
) -> tuple[str, str]:
    if role == "admin":
        r = client.post(
            "/relay/v2/auth/register-admin",
            json={
                "node_name": node_name,
                "bootstrap_secret": secret,
                "capabilities": caps,
            },
        )
        assert r.status_code == 200, r.json()
        body = r.json()
        return body["node_id"], body["token"]

    r = client.post(
        "/relay/v2/auth/register",
        json={
            "node_name": node_name,
            "endpoint": "http://localhost:9001",
            "capabilities": caps,
            "role": role,
        },
    )
    assert r.status_code == 200, r.json()
    worker_id = r.json()["node_id"]

    approval_token = admin_token or _admin_token(secret)
    r2 = client.post(
        f"/relay/v2/admin/nodes/{worker_id}/approve",
        headers={"Authorization": f"Bearer {approval_token}"},
        json={"role": role, "capabilities": caps},
    )
    assert r2.status_code == 200, r2.json()
    return worker_id, r2.json()["token"]


def test_create_task_and_view():
    secret = _seed_admin()
    admin_id, admin_token = _register(
        secret, "Admin", [{"name": "admin", "version": "1.0"}], "admin"
    )

    r = client.post(
        "/relay/v2/scheduler/tasks",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "task_name": "Summarize thread",
            "stages": [
                {
                    "stage_name": "fetch",
                    "capability": "web_fetch",
                    "payload": {"url": "http://example.com"},
                },
                {
                    "stage_name": "summarize",
                    "capability": "llm",
                    "payload": {"model": "gpt-4o-mini"},
                },
            ],
            "priority": 5,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["task"]["task_name"] == "Summarize thread"
    assert body["task"]["status"] == "pending"
    assert len(body["stages"]) == 2
    assert body["stages"][0]["capability"] == "web_fetch"
    assert body["stages"][1]["capability"] == "llm"
    assert body["stages"][1]["depends_on"] == [body["stages"][0]["stage_id"]]

    task_id = body["task"]["task_id"]

    # Fetch via task endpoint
    r = client.get(
        f"/relay/v2/scheduler/tasks/{task_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    assert r.json()["task"]["task_id"] == task_id


def test_claim_and_complete_linear_stage():
    secret = _seed_admin()
    admin_id, admin_token = _register(
        secret, "Admin", [{"name": "admin", "version": "1.0"}], "admin"
    )
    web_id, web_token = _register(
        secret, "Web Node", [{"name": "web_fetch", "version": "1.0"}], admin_token=admin_token
    )
    llm_id, llm_token = _register(
        secret, "LLM Node", [{"name": "llm", "version": "1.0"}], admin_token=admin_token
    )

    r = client.post(
        "/relay/v2/scheduler/tasks",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "task_name": "Summarize",
            "stages": [
                {"stage_name": "fetch", "capability": "web_fetch"},
                {"stage_name": "summarize", "capability": "llm"},
            ],
        },
    )
    task = r.json()
    stage_fetch = task["stages"][0]["stage_id"]
    stage_llm = task["stages"][1]["stage_id"]

    # LLM node should not be able to claim first stage (dependency not ready).
    r = client.post(
        "/relay/v2/scheduler/claim", headers={"Authorization": f"Bearer {llm_token}"}, json={}
    )
    assert r.json()["claimed"] is False

    # Web node claims fetch stage.
    r = client.post(
        "/relay/v2/scheduler/claim", headers={"Authorization": f"Bearer {web_token}"}, json={}
    )
    assert r.status_code == 200
    assert r.json()["claimed"] is True
    assert r.json()["stage"]["stage_id"] == stage_fetch
    assert r.json()["stage"]["claimed_by"] == web_id

    # Complete fetch stage.
    r = client.post(
        f"/relay/v2/scheduler/stages/{stage_fetch}/complete",
        headers={"Authorization": f"Bearer {web_token}"},
        json={"result": {"content": "raw text"}},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "completed"

    # Now LLM node can claim summarize stage.
    r = client.post(
        "/relay/v2/scheduler/claim", headers={"Authorization": f"Bearer {llm_token}"}, json={}
    )
    assert r.json()["claimed"] is True
    assert r.json()["stage"]["stage_id"] == stage_llm

    # Complete summarize stage.
    r = client.post(
        f"/relay/v2/scheduler/stages/{stage_llm}/complete",
        headers={"Authorization": f"Bearer {llm_token}"},
        json={"result": {"summary": "short summary"}},
    )
    assert r.status_code == 200

    # Task should be completed.
    r = client.get(
        f"/relay/v2/scheduler/tasks/{task['task']['task_id']}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.json()["task"]["status"] == "completed"


def test_wrong_node_cannot_complete_stage():
    secret = _seed_admin()
    admin_id, admin_token = _register(
        secret, "Admin", [{"name": "admin", "version": "1.0"}], "admin"
    )
    web_id, web_token = _register(
        secret, "Web Node", [{"name": "web_fetch", "version": "1.0"}], admin_token=admin_token
    )
    other_id, other_token = _register(
        secret, "Other Node", [{"name": "web_fetch", "version": "1.0"}], admin_token=admin_token
    )

    r = client.post(
        "/relay/v2/scheduler/tasks",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"task_name": "T", "stages": [{"stage_name": "fetch", "capability": "web_fetch"}]},
    )
    stage_id = r.json()["stages"][0]["stage_id"]

    client.post(
        "/relay/v2/scheduler/claim", headers={"Authorization": f"Bearer {web_token}"}, json={}
    )

    r = client.post(
        f"/relay/v2/scheduler/stages/{stage_id}/complete",
        headers={"Authorization": f"Bearer {other_token}"},
        json={},
    )
    assert r.status_code == 404


def test_artifact_upload_and_list():
    secret = _seed_admin()
    admin_id, admin_token = _register(
        secret, "Admin", [{"name": "admin", "version": "1.0"}], "admin"
    )

    r = client.post(
        "/relay/v2/scheduler/tasks",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"task_name": "With artifact", "stages": [{"stage_name": "s1", "capability": "x"}]},
    )
    task_id = r.json()["task"]["task_id"]

    r = client.post(
        f"/relay/v2/scheduler/artifacts/{task_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
        files={"file": ("test.txt", b"hello world", "text/plain")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "test.txt"
    assert body["size_bytes"] == 11
    assert body["created_by"] == admin_id

    r = client.get(
        f"/relay/v2/scheduler/artifacts/{task_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    assert len(r.json()["artifacts"]) == 1
    assert r.json()["artifacts"][0]["size_bytes"] == 11


def test_task_payload_too_large():
    """Task mit payload > max_payload_bytes muss 422 zurueckgeben."""
    secret = _seed_admin()
    admin_id, admin_token = _register(
        secret, "Admin", [{"name": "admin", "version": "1.0"}], "admin"
    )

    from relay_server.config import settings

    # Ein Payload, der groesser ist als das Limit
    big_payload = {"data": "x" * (settings.max_payload_bytes + 1)}

    r = client.post(
        "/relay/v2/scheduler/tasks",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "task_name": "big-payload-test",
            "stages": [{
                "stage_name": "main",
                "capability": "test.ai",
                "payload": big_payload,
            }],
        },
    )
    assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"


# ---------------------------------------------------------------------------
# T-016: Lock-Retry Tests
# ---------------------------------------------------------------------------


def test_db_write_retries_on_locked():
    """Scheduler retries write when DB is locked."""
    from relay_server.core.scheduler import _retry_db_write

    call_count = 0

    @_retry_db_write
    def flaky_write():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise sqlite3.OperationalError("database is locked")
        return "ok"

    result = flaky_write()
    assert result == "ok"
    assert call_count == 3


def test_db_write_raises_after_exhausted_retries():
    """Scheduler raises after all retries exhausted."""
    from relay_server.core.scheduler import _retry_db_write, _LOCKED_RETRIES

    call_count = 0

    @_retry_db_write
    def always_locked():
        nonlocal call_count
        call_count += 1
        raise sqlite3.OperationalError("database is locked")

    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        always_locked()
    assert call_count == _LOCKED_RETRIES


def test_db_write_does_not_retry_non_lock_error():
    """Non-lock OperationalErrors must propagate immediately."""
    from relay_server.core.scheduler import _retry_db_write

    call_count = 0

    @_retry_db_write
    def other_error():
        nonlocal call_count
        call_count += 1
        raise sqlite3.OperationalError("no such table: foo")

    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        other_error()
    assert call_count == 1


# ---------------------------------------------------------------------------
# T-017: Timeout Enforcement Tests
# ---------------------------------------------------------------------------


def test_enforce_timeouts_marks_overdue_stages():
    """A claimed stage past its timeout is marked timed_out."""
    secret = _seed_admin()
    admin_id, admin_token = _register(
        secret, "Admin", [{"name": "admin", "version": "1.0"}], "admin"
    )
    worker_id, worker_token = _register(
        secret, "Worker", [{"name": "test_ai", "version": "1.0"}], admin_token=admin_token
    )

    # Create a task with a very short timeout.
    r = client.post(
        "/relay/v2/scheduler/tasks",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "task_name": "timeout-test",
            "stages": [{"stage_name": "s1", "capability": "test_ai", "timeout_seconds": 1}],
        },
    )
    assert r.status_code == 200
    stage_id = r.json()["stages"][0]["stage_id"]

    # Claim the stage.
    r = client.post(
        "/relay/v2/scheduler/claim",
        headers={"Authorization": f"Bearer {worker_token}"},
        json={},
    )
    assert r.json()["claimed"] is True

    # Manually backdate claimed_at to force timeout.
    import datetime

    conn = get_conn()
    old_time = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)).isoformat()
    conn.execute(
        "UPDATE task_stages SET claimed_at = ? WHERE stage_id = ?",
        (old_time, stage_id),
    )
    conn.commit()
    conn.close()

    # Enforce timeouts.
    r = client.post(
        "/relay/v2/scheduler/enforce-timeouts",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert stage_id in body["stages_timed_out"]

    # Single-stage task with all stages timed_out -> task itself timed_out.
    assert len(body["tasks_timed_out"]) == 1
    timed_out_task_id = body["tasks_timed_out"][0]

    # Verify stage is timed_out.
    r = client.get(
        f"/relay/v2/scheduler/tasks/{timed_out_task_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    task = r.json()
    assert task["task"]["status"] == "timed_out"
    stage = task["task_stages"][0] if "task_stages" in task else None
    # StageSummary lives under "stages"
    stages = task.get("stages", [])
    assert any(s["status"] == "timed_out" for s in stages)


def test_enforce_timeouts_noop_when_none_overdue():
    """enforce_timeouts returns empty lists when nothing is overdue."""
    secret = _seed_admin()
    admin_id, admin_token = _register(
        secret, "Admin", [{"name": "admin", "version": "1.0"}], "admin"
    )

    r = client.post(
        "/relay/v2/scheduler/enforce-timeouts",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    assert r.json() == {"stages_timed_out": [], "tasks_timed_out": []}


def test_enforce_timeouts_does_not_touch_pending_stage():
    """A pending (not yet claimed) stage is unaffected by timeout enforcement."""
    secret = _seed_admin()
    admin_id, admin_token = _register(
        secret, "Admin", [{"name": "admin", "version": "1.0"}], "admin"
    )

    r = client.post(
        "/relay/v2/scheduler/tasks",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "task_name": "pending-only",
            "stages": [{"stage_name": "s1", "capability": "test_ai", "timeout_seconds": 1}],
        },
    )
    assert r.status_code == 200
    task_id = r.json()["task"]["task_id"]

    r = client.post(
        "/relay/v2/scheduler/enforce-timeouts",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body == {"stages_timed_out": [], "tasks_timed_out": []}

    # Task still pending (no claim happened).
    r = client.get(
        f"/relay/v2/scheduler/tasks/{task_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.json()["task"]["status"] == "pending"


# ---------------------------------------------------------------------------
# T-026: normalized node_capabilities table
# ---------------------------------------------------------------------------


def test_node_capabilities_table_populated_on_registration():
    """Registering a node populates the node_capabilities index (T-026)."""
    from relay_server.core.db import get_node_capability_names, nodes_with_capability

    secret = _seed_admin()
    admin_id, admin_token = _register(
        secret, "Admin", [{"name": "admin", "version": "1.0"}], "admin"
    )
    web_id, _ = _register(
        secret,
        "Web Node",
        [{"name": "web_fetch", "version": "1.0", "type": "io"},
         {"name": "render", "version": "2.0"}],
        admin_token=admin_token,
    )

    # The admin node advertises "admin".
    assert "admin" in get_node_capability_names(admin_id)
    # The web node advertises web_fetch and render.
    web_caps = get_node_capability_names(web_id)
    assert "web_fetch" in web_caps
    assert "render" in web_caps

    # nodes_with_capability returns the registered node for web_fetch.
    nodes = nodes_with_capability("web_fetch")
    assert web_id in nodes


def test_node_capabilities_synced_on_heartbeat_replace():
    """A heartbeat with replace_capabilities refreshes the index (T-026)."""
    from relay_server.core.db import get_node_capability_names

    secret = _seed_admin()
    admin_id, admin_token = _register(
        secret, "Admin", [{"name": "admin", "version": "1.0"}], "admin"
    )
    web_id, web_token = _register(
        secret, "Web Node", [{"name": "web_fetch", "version": "1.0"}], admin_token=admin_token
    )
    assert "web_fetch" in get_node_capability_names(web_id)

    # Replace capabilities via worker heartbeat (replace mode).
    r = client.post(
        "/relay/v2/discovery/worker-heartbeat",
        headers={"Authorization": f"Bearer {web_token}"},
        json={
            "node_id": web_id,
            "load": 0.0,
            "queue_depth": 0,
            "available": True,
            "capabilities": [{"name": "new_cap", "version": "1.0"}],
        },
    )
    assert r.status_code == 200, r.json()

    web_caps = get_node_capability_names(web_id)
    assert "new_cap" in web_caps
    assert "web_fetch" not in web_caps


def test_claim_stage_uses_normalized_index():
    """claim_stage without an explicit capability uses node_capabilities (T-026)."""
    secret = _seed_admin()
    admin_id, admin_token = _register(
        secret, "Admin", [{"name": "admin", "version": "1.0"}], "admin"
    )
    worker_id, worker_token = _register(
        secret, "Worker", [{"name": "chat", "version": "1.0"}], admin_token=admin_token
    )

    # Create a task with a chat stage.
    r = client.post(
        "/relay/v2/scheduler/tasks",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "task_name": "Chat task",
            "stages": [{"stage_name": "do-chat", "capability": "chat"}],
        },
    )
    assert r.status_code == 200

    # Worker claims without specifying capability — the scheduler must
    # derive "chat" from the normalized index.
    r = client.post(
        "/relay/v2/scheduler/claim",
        headers={"Authorization": f"Bearer {worker_token}"},
        json={},
    )
    assert r.status_code == 200
    assert r.json()["claimed"] is True
    assert r.json()["stage"]["capability"] == "chat"


# ---------------------------------------------------------------------------
# T-046: owner_node_id restricts which node may claim a stage
# ---------------------------------------------------------------------------


def test_claim_stage_respects_owner_node_id():
    """A task with owner_node_id set can only be claimed by that node."""
    secret = _seed_admin()
    admin_id, admin_token = _register(
        secret, "Admin", [{"name": "admin", "version": "1.0"}], "admin"
    )
    node_a_id, node_a_token = _register(
        secret, "Node A", [{"name": "chat", "version": "1.0"}], admin_token=admin_token
    )
    node_b_id, node_b_token = _register(
        secret, "Node B", [{"name": "chat", "version": "1.0"}], admin_token=admin_token
    )

    # Submit a task pinned to Node A via owner_node_id.
    r = client.post(
        "/relay/v2/scheduler/tasks",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "task_name": "Pinned",
            "stages": [{"stage_name": "do-chat", "capability": "chat"}],
            "owner_node_id": node_a_id,
        },
    )
    assert r.status_code == 200, r.json()
    task_id = r.json()["task"]["task_id"]
    stage_id = r.json()["stages"][0]["stage_id"]

    # Node B has the matching capability but must NOT be able to claim.
    r = client.post(
        "/relay/v2/scheduler/claim",
        headers={"Authorization": f"Bearer {node_b_token}"},
        json={},
    )
    assert r.status_code == 200
    assert r.json()["claimed"] is False

    # The stage is still pending — Node B was skipped, not claimed.
    conn = get_conn()
    row = conn.execute(
        "SELECT status, claimed_by FROM task_stages WHERE stage_id = ?",
        (stage_id,),
    ).fetchone()
    conn.close()
    assert row["status"] == "pending"
    assert row["claimed_by"] is None

    # Node A is the owner and may claim.
    r = client.post(
        "/relay/v2/scheduler/claim",
        headers={"Authorization": f"Bearer {node_a_token}"},
        json={},
    )
    assert r.status_code == 200
    assert r.json()["claimed"] is True
    assert r.json()["stage"]["stage_id"] == stage_id
    assert r.json()["stage"]["claimed_by"] == node_a_id
