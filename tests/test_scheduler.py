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


# ---------------------------------------------------------------------------
# T-052: task notes (mini-chat between nodes)
# ---------------------------------------------------------------------------


def test_add_note_and_get_task_returns_notes():
    """POST /tasks/{id}/notes adds a note; GET /tasks/{id} returns it."""
    secret = _seed_admin()
    admin_id, admin_token = _register(
        secret, "Admin", [{"name": "admin", "version": "1.0"}], "admin"
    )

    # Create a task.
    r = client.post(
        "/relay/v2/scheduler/tasks",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"task_name": "With notes", "stages": [{"stage_name": "s1", "capability": "x"}]},
    )
    assert r.status_code == 200
    task_id = r.json()["task"]["task_id"]

    # Initial GET has no notes.
    r = client.get(
        f"/relay/v2/scheduler/tasks/{task_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    assert r.json()["notes"] == []

    # Add a note.
    r = client.post(
        f"/relay/v2/scheduler/tasks/{task_id}/notes",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"message": "starting work"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["task_id"] == task_id
    assert body["node_id"] == admin_id
    assert body["message"] == "starting work"
    assert body["created_at"]
    note_id = body["id"]
    assert isinstance(note_id, int)

    # GET now includes the note.
    r = client.get(
        f"/relay/v2/scheduler/tasks/{task_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    notes = r.json()["notes"]
    assert len(notes) == 1
    assert notes[0]["id"] == note_id
    assert notes[0]["node_id"] == admin_id
    assert notes[0]["message"] == "starting work"

    # Add a second note — ordering must be preserved (asc by created_at).
    r = client.post(
        f"/relay/v2/scheduler/tasks/{task_id}/notes",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"message": "done"},
    )
    assert r.status_code == 200

    r = client.get(
        f"/relay/v2/scheduler/tasks/{task_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    notes = r.json()["notes"]
    assert len(notes) == 2
    assert notes[0]["message"] == "starting work"
    assert notes[1]["message"] == "done"


def test_add_note_to_unknown_task_returns_404():
    """POST /tasks/{id}/notes returns 404 for a missing task."""
    secret = _seed_admin()
    admin_id, admin_token = _register(
        secret, "Admin", [{"name": "admin", "version": "1.0"}], "admin"
    )

    r = client.post(
        "/relay/v2/scheduler/tasks/task_does_not_exist/notes",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"message": "hello"},
    )
    assert r.status_code == 404


def test_add_note_rejects_empty_and_oversize_message():
    """Empty messages are rejected (422); over-2000-char messages too."""
    secret = _seed_admin()
    admin_id, admin_token = _register(
        secret, "Admin", [{"name": "admin", "version": "1.0"}], "admin"
    )

    r = client.post(
        "/relay/v2/scheduler/tasks",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"task_name": "n", "stages": [{"stage_name": "s1", "capability": "x"}]},
    )
    task_id = r.json()["task"]["task_id"]

    # Empty message -> 422 (pydantic min_length=1).
    r = client.post(
        f"/relay/v2/scheduler/tasks/{task_id}/notes",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"message": ""},
    )
    assert r.status_code == 422

    # Over limit -> 422.
    r = client.post(
        f"/relay/v2/scheduler/tasks/{task_id}/notes",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"message": "x" * 2001},
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# T-053: capability_details on claim and task-view
# ---------------------------------------------------------------------------


def _register_worker_with_meta(secret, admin_token, name, cap_dict):
    """Register + approve a worker with a full capability dict (description/type/input_schema)."""
    worker_id, worker_token = _register(
        secret, name, [cap_dict], admin_token=admin_token
    )
    return worker_id, worker_token


def test_claim_response_includes_capability_details():
    """claim_stage attaches capability_details from the claiming node's heartbeat."""
    secret = _seed_admin()
    admin_id, admin_token = _register(
        secret, "Admin", [{"name": "admin", "version": "1.0"}], "admin"
    )
    worker_id, worker_token = _register_worker_with_meta(
        secret,
        admin_token,
        "Worker With Schema",
        {
            "name": "chat.ai",
            "version": "1.0.0",
            "type": "ai",
            "description": "General conversational AI.",
            "input_schema": {"fields": {"prompt": {"type": "string"}}},
        },
    )

    # Heartbeat so the metadata lands in node_capabilities.
    r = client.post(
        "/relay/v2/discovery/worker-heartbeat",
        headers={"Authorization": f"Bearer {worker_token}"},
        json={
            "node_id": worker_id,
            "available": True,
            "capabilities": [
                {
                    "name": "chat.ai",
                    "version": "1.0.0",
                    "type": "ai",
                    "description": "General conversational AI.",
                    "input_schema": {"fields": {"prompt": {"type": "string"}}},
                }
            ],
        },
    )
    assert r.status_code == 200

    # Submit a task with a chat.ai stage.
    r = client.post(
        "/relay/v2/scheduler/tasks",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "task_name": "chat-task",
            "stages": [{"stage_name": "do-chat", "capability": "chat.ai"}],
        },
    )
    assert r.status_code == 200
    task_id = r.json()["task"]["task_id"]

    # Worker claims — capability_details must be present.
    r = client.post(
        "/relay/v2/scheduler/claim",
        headers={"Authorization": f"Bearer {worker_token}"},
        json={},
    )
    assert r.status_code == 200
    assert r.json()["claimed"] is True
    stage = r.json()["stage"]
    assert stage["capability"] == "chat.ai"
    cd = stage.get("capability_details")
    assert cd is not None, "capability_details missing on claim response"
    assert cd["name"] == "chat.ai"
    assert cd["type"] == "ai"
    assert cd["description"] == "General conversational AI."
    assert cd["input_schema"] == {"fields": {"prompt": {"type": "string"}}}


def test_task_view_includes_capability_details_per_stage():
    """GET /tasks/{id} resolves capability_details for each stage."""
    secret = _seed_admin()
    admin_id, admin_token = _register(
        secret, "Admin", [{"name": "admin", "version": "1.0"}], "admin"
    )
    worker_id, worker_token = _register_worker_with_meta(
        secret,
        admin_token,
        "Worker For View",
        {
            "name": "render.native",
            "version": "1.0.0",
            "type": "tool",
            "description": "Render a template.",
            "input_schema": {"fields": {"template": {"type": "string"}}},
        },
    )

    # Heartbeat with the metadata.
    r = client.post(
        "/relay/v2/discovery/worker-heartbeat",
        headers={"Authorization": f"Bearer {worker_token}"},
        json={
            "node_id": worker_id,
            "available": True,
            "capabilities": [
                {
                    "name": "render.native",
                    "version": "1.0.0",
                    "type": "tool",
                    "description": "Render a template.",
                    "input_schema": {"fields": {"template": {"type": "string"}}},
                }
            ],
        },
    )
    assert r.status_code == 200

    # Submit a task with a render.native stage.
    r = client.post(
        "/relay/v2/scheduler/tasks",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "task_name": "render-task",
            "stages": [{"stage_name": "render-it", "capability": "render.native"}],
        },
    )
    task_id = r.json()["task"]["task_id"]

    # GET task view — capability_details must be on the stage even before claim.
    r = client.get(
        f"/relay/v2/scheduler/tasks/{task_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    stages = r.json()["stages"]
    assert len(stages) == 1
    cd = stages[0].get("capability_details")
    assert cd is not None
    assert cd["name"] == "render.native"
    assert cd["type"] == "tool"
    assert cd["description"] == "Render a template."
    assert cd["input_schema"] == {"fields": {"template": {"type": "string"}}}


def test_task_view_capability_details_absent_for_unknown_capability():
    """When no node advertises the capability, capability_details is absent."""
    secret = _seed_admin()
    admin_id, admin_token = _register(
        secret, "Admin", [{"name": "admin", "version": "1.0"}], "admin"
    )

    # Submit a task for a capability no node offers.
    r = client.post(
        "/relay/v2/scheduler/tasks",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "task_name": "unknown-cap",
            "stages": [{"stage_name": "s1", "capability": "no.such.cap"}],
        },
    )
    task_id = r.json()["task"]["task_id"]

    r = client.get(
        f"/relay/v2/scheduler/tasks/{task_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    stages = r.json()["stages"]
    assert len(stages) == 1
    # capability_details is optional; it must simply be absent, not malformed.
    assert stages[0].get("capability_details") is None


def test_db_migration_adds_node_capability_schema_columns(tmp_path):
    """A pre-existing DB without description/input_schema columns is migrated.

    Regression guard for the ALTER TABLE migration added in T-053.
    """
    import sqlite3

    from relay_server.config import settings
    from relay_server.core.db import init_db_for_path

    db = tmp_path / "legacy.db"
    # Create a full schema first (as _schema would), then drop the two columns
    # to simulate a pre-T-053 database.
    conn = sqlite3.connect(str(db))
    conn.execute("""
        CREATE TABLE nodes (
            node_id TEXT PRIMARY KEY,
            capabilities TEXT,
            status TEXT DEFAULT 'approved',
            role TEXT DEFAULT 'worker',
            node_name TEXT,
            endpoint TEXT,
            last_seen TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE tasks (
            task_id TEXT PRIMARY KEY,
            task_name TEXT,
            status TEXT DEFAULT 'pending',
            priority INTEGER DEFAULT 0,
            owner_node_id TEXT,
            timeout_seconds INTEGER,
            created_at TEXT,
            updated_at TEXT,
            completed_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE task_stages (
            stage_id TEXT PRIMARY KEY,
            task_id TEXT,
            stage_name TEXT,
            capability TEXT,
            status TEXT DEFAULT 'pending',
            depends_on TEXT,
            sequence INTEGER DEFAULT 0,
            timeout_seconds INTEGER,
            payload TEXT,
            claimed_by TEXT,
            claimed_at TEXT,
            claim_expires_at TEXT,
            completed_at TEXT,
            result TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE audit_logs (
            log_id TEXT PRIMARY KEY,
            actor_id TEXT,
            action TEXT,
            target_type TEXT,
            target_id TEXT,
            details TEXT,
            created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE node_tokens (
            token_id TEXT PRIMARY KEY,
            node_id TEXT,
            token_type TEXT,
            token_hash TEXT,
            credential_type TEXT,
            expires_at TEXT,
            created_at TEXT,
            revoked INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE users (
            user_id TEXT PRIMARY KEY,
            username TEXT UNIQUE,
            password_hash TEXT,
            created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE user_groups (
            user_id TEXT,
            group_name TEXT,
            PRIMARY KEY (user_id, group_name)
        )
    """)
    conn.execute("""
        CREATE TABLE group_permissions (
            group_id TEXT,
            permission_id TEXT,
            granted_at TEXT,
            PRIMARY KEY (group_id, permission_id)
        )
    """)
    conn.execute("""
        CREATE TABLE permissions (
            permission_id TEXT PRIMARY KEY,
            permission_name TEXT,
            description TEXT,
            created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE seeds (
            seed_id TEXT PRIMARY KEY,
            seed_hash TEXT,
            created_by TEXT,
            created_at TEXT,
            expires_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE artifacts (
            artifact_id TEXT PRIMARY KEY,
            name TEXT,
            mime_type TEXT,
            size_bytes INTEGER,
            storage_path TEXT,
            task_id TEXT,
            stage_id TEXT,
            created_by TEXT,
            created_at TEXT
        )
    """)
    # Create node_capabilities WITHOUT description/input_schema (pre-T-053 state)
    conn.execute("""
        CREATE TABLE node_capabilities (
            node_id TEXT NOT NULL,
            capability_name TEXT NOT NULL,
            capability_type TEXT,
            capability_version TEXT DEFAULT '1.0.0',
            available BOOLEAN DEFAULT 1,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (node_id, capability_name),
            FOREIGN KEY (node_id) REFERENCES nodes(node_id) ON DELETE CASCADE
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_node_capabilities_name "
        "ON node_capabilities(capability_name)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_node_capabilities_name_type "
        "ON node_capabilities(capability_name, capability_type)"
    )
    conn.commit()
    conn.close()

    # Run init_db_for_path on the legacy DB — migration must add columns.
    init_db_for_path(str(db))

    conn = sqlite3.connect(str(db))
    cols = [r[1] for r in conn.execute("PRAGMA table_info(node_capabilities)").fetchall()]
    conn.close()
    assert "description" in cols
    assert "input_schema" in cols


def test_db_migration_creates_task_notes_table(tmp_path):
    """A pre-existing DB without task_notes gets the table on init (T-052)."""
    import sqlite3

    from relay_server.core.db import init_db_for_path

    db = tmp_path / "legacy_no_notes.db"
    # Create a full schema (as _schema would) but WITHOUT task_notes.
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE nodes (node_id TEXT PRIMARY KEY, capabilities TEXT, status TEXT DEFAULT 'approved', role TEXT DEFAULT 'worker', node_name TEXT, endpoint TEXT, last_seen TEXT, created_at TEXT, updated_at TEXT)")
    conn.execute("CREATE TABLE tasks (task_id TEXT PRIMARY KEY, task_name TEXT, status TEXT DEFAULT 'pending', priority INTEGER DEFAULT 0, owner_node_id TEXT, timeout_seconds INTEGER, created_at TEXT, updated_at TEXT, completed_at TEXT)")
    conn.execute("CREATE TABLE task_stages (stage_id TEXT PRIMARY KEY, task_id TEXT, stage_name TEXT, capability TEXT, status TEXT DEFAULT 'pending', depends_on TEXT, sequence INTEGER DEFAULT 0, timeout_seconds INTEGER, payload TEXT, claimed_by TEXT, claimed_at TEXT, claim_expires_at TEXT, completed_at TEXT, result TEXT, created_at TEXT, updated_at TEXT)")
    conn.execute("CREATE TABLE audit_logs (log_id TEXT PRIMARY KEY, actor_id TEXT, action TEXT, target_type TEXT, target_id TEXT, details TEXT, created_at TEXT)")
    conn.execute("CREATE TABLE node_tokens (token_id TEXT PRIMARY KEY, node_id TEXT, token_type TEXT, token_hash TEXT, credential_type TEXT, expires_at TEXT, created_at TEXT, revoked INTEGER DEFAULT 0)")
    conn.execute("CREATE TABLE users (user_id TEXT PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT, created_at TEXT)")
    conn.execute("CREATE TABLE user_groups (user_id TEXT, group_name TEXT, PRIMARY KEY (user_id, group_name))")
    conn.execute("CREATE TABLE group_permissions (group_id TEXT, permission_id TEXT, granted_at TEXT, PRIMARY KEY (group_id, permission_id))")
    conn.execute("CREATE TABLE permissions (permission_id TEXT PRIMARY KEY, permission_name TEXT, description TEXT, created_at TEXT)")
    conn.execute("CREATE TABLE seeds (seed_id TEXT PRIMARY KEY, seed_hash TEXT, created_by TEXT, created_at TEXT, expires_at TEXT)")
    conn.execute("CREATE TABLE artifacts (artifact_id TEXT PRIMARY KEY, name TEXT, mime_type TEXT, size_bytes INTEGER, storage_path TEXT, task_id TEXT, stage_id TEXT, created_by TEXT, created_at TEXT)")
    conn.execute("CREATE TABLE node_capabilities (node_id TEXT NOT NULL, capability_name TEXT NOT NULL, capability_type TEXT, capability_version TEXT DEFAULT '1.0.0', description TEXT, input_schema TEXT, available BOOLEAN DEFAULT 1, updated_at TEXT NOT NULL, PRIMARY KEY (node_id, capability_name))")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_node_capabilities_name ON node_capabilities(capability_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_node_capabilities_name_type ON node_capabilities(capability_name, capability_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_logs_actor ON audit_logs(actor_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_logs_created ON audit_logs(created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_task_id ON artifacts(task_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_node_tokens_node_id ON node_tokens(node_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_node_tokens_expires ON node_tokens(expires_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_task_stages_task_id ON task_stages(task_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_task_stages_status ON task_stages(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_task_stages_capability ON task_stages(capability)")
    conn.commit()
    conn.close()

    init_db_for_path(str(db))

    conn = sqlite3.connect(str(db))
    tables = [
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    ]
    conn.close()
    assert "task_notes" in tables


# ---------------------------------------------------------------------------
# T-060 / T-061: retry_count migration + release_or_fail_claims + offline
# ---------------------------------------------------------------------------


def test_db_migration_adds_retry_count_column(tmp_path):
    """A pre-existing task_stages table without retry_count gets it on init."""
    import sqlite3

    from relay_server.core.db import init_db_for_path

    db = tmp_path / "legacy_no_retry.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE nodes (node_id TEXT PRIMARY KEY, capabilities TEXT, status TEXT DEFAULT 'approved', role TEXT DEFAULT 'worker', node_name TEXT, endpoint TEXT, last_seen TEXT, created_at TEXT, updated_at TEXT)")
    conn.execute("CREATE TABLE tasks (task_id TEXT PRIMARY KEY, task_name TEXT, status TEXT DEFAULT 'pending', priority INTEGER DEFAULT 0, owner_node_id TEXT, timeout_seconds INTEGER, created_at TEXT, updated_at TEXT, completed_at TEXT)")
    # task_stages WITHOUT retry_count (pre-T-060 state).
    conn.execute("CREATE TABLE task_stages (stage_id TEXT PRIMARY KEY, task_id TEXT, stage_name TEXT, capability TEXT, status TEXT DEFAULT 'pending', depends_on TEXT, sequence INTEGER DEFAULT 0, timeout_seconds INTEGER, payload TEXT, claimed_by TEXT, claimed_at TEXT, claim_expires_at TEXT, completed_at TEXT, result TEXT, created_at TEXT, updated_at TEXT)")
    conn.execute("CREATE TABLE audit_logs (log_id TEXT PRIMARY KEY, actor_id TEXT, action TEXT, created_at TEXT)")
    conn.execute("CREATE TABLE node_tokens (token_id TEXT PRIMARY KEY, node_id TEXT, token_type TEXT, token_hash TEXT, expires_at TEXT, created_at TEXT)")
    conn.execute("CREATE TABLE users (user_id TEXT PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT, created_at TEXT)")
    conn.execute("CREATE TABLE user_groups (user_id TEXT, group_name TEXT, PRIMARY KEY (user_id, group_name))")
    conn.execute("CREATE TABLE group_permissions (group_id TEXT, permission_id TEXT, granted_at TEXT, PRIMARY KEY (group_id, permission_id))")
    conn.execute("CREATE TABLE permissions (permission_id TEXT PRIMARY KEY, permission_name TEXT, description TEXT, created_at TEXT)")
    conn.execute("CREATE TABLE artifacts (artifact_id TEXT PRIMARY KEY, name TEXT, mime_type TEXT, size_bytes INTEGER, storage_path TEXT, task_id TEXT, stage_id TEXT, created_by TEXT, created_at TEXT)")
    conn.execute("CREATE TABLE node_capabilities (node_id TEXT NOT NULL, capability_name TEXT NOT NULL, capability_type TEXT, capability_version TEXT DEFAULT '1.0.0', description TEXT, input_schema TEXT, available BOOLEAN DEFAULT 1, updated_at TEXT NOT NULL, PRIMARY KEY (node_id, capability_name))")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_node_capabilities_name ON node_capabilities(capability_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_node_capabilities_name_type ON node_capabilities(capability_name, capability_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_task_stages_task_id ON task_stages(task_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_task_stages_status ON task_stages(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_task_stages_capability ON task_stages(capability)")
    conn.commit()
    conn.close()

    init_db_for_path(str(db))

    conn = sqlite3.connect(str(db))
    cols = [r[1] for r in conn.execute("PRAGMA table_info(task_stages)").fetchall()]
    conn.close()
    assert "retry_count" in cols


def _claim_a_stage(admin_token: str, worker_token: str) -> tuple[str, str, str]:
    """Helper: create a single-stage task and claim it. Returns (task_id, stage_id, worker_id_from_claim)."""
    r = client.post(
        "/relay/v2/scheduler/tasks",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"task_name": "retry-test", "stages": [{"stage_name": "s1", "capability": "test_ai"}]},
    )
    assert r.status_code == 200, r.json()
    task_id = r.json()["task"]["task_id"]
    stage_id = r.json()["stages"][0]["stage_id"]

    r = client.post(
        "/relay/v2/scheduler/claim",
        headers={"Authorization": f"Bearer {worker_token}"},
        json={},
    )
    assert r.json()["claimed"] is True
    assert r.json()["stage"]["stage_id"] == stage_id
    return task_id, stage_id, r.json()["stage"]["claimed_by"]


def _backdate_claim_expiry(stage_id: str) -> None:
    """Force claim_expires_at into the past so release_or_fail_claims picks it up."""
    import datetime

    past = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)).isoformat()
    conn = get_conn()
    conn.execute(
        "UPDATE task_stages SET claim_expires_at = ? WHERE stage_id = ?",
        (past, stage_id),
    )
    conn.commit()
    conn.close()


def test_release_or_fail_claims_releases_within_budget():
    """First TTL expiry within max_retries puts the stage back to pending and bumps retry_count."""
    from relay_server.core.scheduler import Scheduler

    settings.max_retries = 2
    secret = _seed_admin()
    admin_id, admin_token = _register(
        secret, "Admin", [{"name": "admin", "version": "1.0"}], "admin"
    )
    worker_id, worker_token = _register(
        secret, "Worker", [{"name": "test_ai", "version": "1.0"}], admin_token=admin_token
    )

    task_id, stage_id, _ = _claim_a_stage(admin_token, worker_token)
    _backdate_claim_expiry(stage_id)

    result = Scheduler.release_or_fail_claims()
    assert stage_id in result["released"]
    assert result["failed"] == []
    assert result["tasks_failed"] == []

    conn = get_conn()
    row = conn.execute(
        "SELECT status, retry_count FROM task_stages WHERE stage_id = ?", (stage_id,)
    ).fetchone()
    conn.close()
    assert row["status"] == "pending"
    assert row["retry_count"] == 1


def test_release_or_fail_claims_fails_after_max_retries():
    """Once retry_count exceeds max_retries the stage is marked failed, not pending."""
    from relay_server.core.scheduler import Scheduler

    settings.max_retries = 2
    secret = _seed_admin()
    admin_id, admin_token = _register(
        secret, "Admin", [{"name": "admin", "version": "1.0"}], "admin"
    )
    worker_id, worker_token = _register(
        secret, "Worker", [{"name": "test_ai", "version": "1.0"}], admin_token=admin_token
    )

    task_id, stage_id, _ = _claim_a_stage(admin_token, worker_token)

    # Pre-set retry_count so the next release exceeds max_retries (2):
    # new_count = 3 > 2 → stage failed.
    conn = get_conn()
    conn.execute(
        "UPDATE task_stages SET retry_count = 2 WHERE stage_id = ?", (stage_id,)
    )
    conn.commit()
    conn.close()

    _backdate_claim_expiry(stage_id)

    result = Scheduler.release_or_fail_claims()
    assert result["released"] == []
    assert stage_id in result["failed"]
    # Single-stage task with all stages failed → task failed.
    assert task_id in result["tasks_failed"]

    conn = get_conn()
    stage_row = conn.execute(
        "SELECT status, retry_count FROM task_stages WHERE stage_id = ?", (stage_id,)
    ).fetchone()
    task_row = conn.execute(
        "SELECT status FROM tasks WHERE task_id = ?", (task_id,)
    ).fetchone()
    conn.close()
    assert stage_row["status"] == "failed"
    assert stage_row["retry_count"] == 3
    assert task_row["status"] == "failed"


def test_release_or_fail_claims_noop_when_none_expired():
    """No expired claims → empty result."""
    from relay_server.core.scheduler import Scheduler

    secret = _seed_admin()
    admin_id, admin_token = _register(
        secret, "Admin", [{"name": "admin", "version": "1.0"}], "admin"
    )

    result = Scheduler.release_or_fail_claims()
    assert result == {"released": [], "failed": [], "tasks_failed": []}


def test_stage_row_to_dict_exposes_retry_count():
    """_stage_row_to_dict surfaces retry_count so clients can see retry state."""
    from relay_server.core.scheduler import _stage_row_to_dict

    secret = _seed_admin()
    admin_id, admin_token = _register(
        secret, "Admin", [{"name": "admin", "version": "1.0"}], "admin"
    )
    worker_id, worker_token = _register(
        secret, "Worker", [{"name": "test_ai", "version": "1.0"}], admin_token=admin_token
    )
    task_id, stage_id, _ = _claim_a_stage(admin_token, worker_token)

    # Bump retry_count directly and read the stage back via get_task.
    conn = get_conn()
    conn.execute("UPDATE task_stages SET retry_count = 2 WHERE stage_id = ?", (stage_id,))
    conn.commit()
    conn.close()

    r = client.get(
        f"/relay/v2/scheduler/tasks/{task_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    stages = r.json()["stages"]
    assert len(stages) == 1
    assert stages[0]["retry_count"] == 2


# ---------------------------------------------------------------------------
# T-063: orphaned-stage watchdog integration
# ---------------------------------------------------------------------------


def test_fail_orphaned_stages_integration():
    """End-to-end: a pending stage with no advertising node gets failed."""
    from relay_server.core.scheduler import Scheduler

    secret = _seed_admin()
    admin_id, admin_token = _register(
        secret, "Admin", [{"name": "admin", "version": "1.0"}], "admin"
    )

    # Create a task for a capability no node offers. The admin node only
    # advertises "admin", so "ghost.cap" is uncovered.
    r = client.post(
        "/relay/v2/scheduler/tasks",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "task_name": "orphan-integration",
            "stages": [{"stage_name": "ghost", "capability": "ghost.cap"}],
        },
    )
    assert r.status_code == 200
    task_id = r.json()["task"]["task_id"]
    stage_id = r.json()["stages"][0]["stage_id"]

    result = Scheduler.fail_orphaned_stages()
    assert stage_id in result["stages_failed"]
    assert task_id in result["tasks_failed"]

    # Verify via the public task endpoint that the task ended as failed.
    r = client.get(
        f"/relay/v2/scheduler/tasks/{task_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    assert r.json()["task"]["status"] == "failed"
