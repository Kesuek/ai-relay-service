"""Tests for the central MaintenanceScheduler and its watchdogs (T-049/T-050/T-063)."""

import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ["RELAY_DB_PATH"] = ""
os.environ["RELAY_SESSION_SECRET"] = "test-session-secret-do-not-use-in-production"

from relay_server.config import settings
from relay_server.core.artifacts import cleanup_orphaned_artifacts, store_artifact
from relay_server.core.auth import generate_secret, hash_secret
from relay_server.core.db import get_conn, init_db
from relay_server.core.maintenance import MaintenanceScheduler
from relay_server.core.scheduler import Scheduler
from relay_server.main import app


@pytest.fixture(autouse=True)
def fresh_db():
    """Use a temporary database + artifacts dir per test."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        settings.db_path = tmp_path / "test.db"
        settings.session_secret = "test-session-secret-do-not-use-in-production"
        settings.artifacts_dir = tmp_path / "artifacts"
        settings.chunked_uploads_dir = tmp_path / "chunked_uploads"
        settings.artifact_cleanup_max_age_days = 7.0
        settings.orphaned_stage_interval_seconds = 300
        settings.db_vacuum_interval_seconds = 86400
        import relay_server.core.auth as auth_mod

        auth_mod._TOKEN_PEPPER = None
        init_db()
        yield
        auth_mod._TOKEN_PEPPER = None


client = TestClient(app)


# ---------------------------------------------------------------------------
# MaintenanceScheduler unit tests
# ---------------------------------------------------------------------------


def test_maintenance_scheduler_register_and_run():
    """register + run_all/run_due execute registered callables."""
    sched = MaintenanceScheduler()
    calls = []

    sched.register("noop", lambda: {"done": True}, interval_seconds=100)
    # run_due must run on first call (last_run == 0).
    results = sched.run_due()
    assert "noop" in results
    assert results["noop"] == {"done": True}

    # Second run_due immediately must NOT run (interval not elapsed).
    results = sched.run_due()
    assert results == {}

    # run_all runs regardless of interval.
    results = sched.run_all()
    assert results["noop"] == {"done": True}


def test_maintenance_scheduler_run_due_only_due():
    """Only tasks whose interval has elapsed are run by run_due."""
    import time

    sched = MaintenanceScheduler()
    counter = {"a": 0, "b": 0}

    sched.register("a", lambda: counter.update(a=counter["a"] + 1) or {"a": counter["a"]}, 1)
    sched.register("b", lambda: counter.update(b=counter["b"] + 1) or {"b": counter["b"]}, 1000)

    # First call → both run (last_run == 0).
    sched.run_due()
    assert counter == {"a": 1, "b": 1}

    # Wait >1s so "a" becomes due again, "b" is not.
    time.sleep(1.1)
    sched.run_due()
    assert counter == {"a": 2, "b": 1}


def test_maintenance_scheduler_status():
    """status() reports per-task interval, last_run and next_run."""
    sched = MaintenanceScheduler()
    sched.register("t1", lambda: {}, 60)
    status = sched.status()
    assert len(status) == 1
    entry = status[0]
    assert entry["name"] == "t1"
    assert entry["interval"] == 60
    assert entry["last_run"] == 0.0
    assert entry["next_run"] == 0.0
    assert entry["due"] is True

    sched.run_due()
    status = sched.status()
    assert status[0]["last_run"] > 0
    assert status[0]["due"] is False


def test_maintenance_scheduler_unregister():
    sched = MaintenanceScheduler()
    sched.register("x", lambda: {}, 10)
    assert any(e["name"] == "x" for e in sched.status())
    sched.unregister("x")
    assert sched.status() == []
    # unregister unknown name is a no-op.
    sched.unregister("does-not-exist")


def test_maintenance_scheduler_isolates_errors():
    """A raising task must not abort siblings and is reported as error."""
    sched = MaintenanceScheduler()

    def boom():
        raise RuntimeError("kaboom")

    sibling_ran = {"v": False}

    def sibling():
        sibling_ran["v"] = True
        return {"ok": True}

    sched.register("boom", boom, 1)
    sched.register("sibling", sibling, 1)
    results = sched.run_all()
    assert results["boom"]["error"] == "kaboom"
    assert results["sibling"] == {"ok": True}
    assert sibling_ran["v"] is True


# ---------------------------------------------------------------------------
# cleanup_orphaned_artifacts (T-049)
# ---------------------------------------------------------------------------


def _insert_task(task_id: str = "task_exists") -> None:
    conn = get_conn()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO tasks (task_id, task_name, status, priority, owner_node_id, "
        "timeout_seconds, created_at, updated_at) VALUES (?, ?, 'pending', 0, NULL, 300, ?, ?)",
        (task_id, "Existing", now, now),
    )
    conn.commit()
    conn.close()


def _backdate_artifact(artifact_id: str, days: float = 8.0) -> None:
    old = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    conn = get_conn()
    conn.execute(
        "UPDATE artifacts SET created_at = ? WHERE artifact_id = ?", (old, artifact_id)
    )
    conn.commit()
    conn.close()


def test_cleanup_orphaned_artifacts():
    """Artifact whose task_id no longer exists AND is old enough is deleted."""
    # Artifact pointing to a task that doesn't exist.
    info = store_artifact(
        name="orphan.txt",
        content=b"orphan-bytes",
        task_id="task_gone",
    )
    artifact_id = info["artifact_id"]
    _backdate_artifact(artifact_id, days=8)

    result = cleanup_orphaned_artifacts(max_age_days=7.0)
    assert result["deleted"] == 1
    assert result["freed_bytes"] == len(b"orphan-bytes")

    # DB row gone.
    conn = get_conn()
    row = conn.execute(
        "SELECT artifact_id FROM artifacts WHERE artifact_id = ?", (artifact_id,)
    ).fetchone()
    conn.close()
    assert row is None
    # File gone.
    assert not Path(info["path"]).exists()


def test_cleanup_orphaned_artifacts_keeps_referenced():
    """Artifact pointing to an existing task is kept."""
    _insert_task("task_exists")
    info = store_artifact(
        name="kept.txt",
        content=b"keep",
        task_id="task_exists",
    )
    _backdate_artifact(info["artifact_id"], days=10)

    result = cleanup_orphaned_artifacts(max_age_days=7.0)
    assert result["deleted"] == 0
    assert Path(info["path"]).exists()


def test_cleanup_orphaned_artifacts_respects_age_window():
    """A recent orphan is kept — it might be mid-creation."""
    info = store_artifact(
        name="recent.txt",
        content=b"recent",
        task_id="task_gone",
    )
    # No backdating → created_at is now, within the 7-day window.
    result = cleanup_orphaned_artifacts(max_age_days=7.0)
    assert result["deleted"] == 0
    assert Path(info["path"]).exists()


def test_cleanup_orphaned_artifacts_noop_when_clean():
    """No orphans → empty result."""
    _insert_task("task_exists")
    store_artifact(name="ok.txt", content=b"x", task_id="task_exists")
    result = cleanup_orphaned_artifacts(max_age_days=7.0)
    assert result == {"deleted": 0, "freed_bytes": 0}


# ---------------------------------------------------------------------------
# fail_orphaned_stages (T-063)
# ---------------------------------------------------------------------------


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


def _register(secret, node_name, caps, admin_token=None, role="service"):
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
        return r.json()["node_id"], r.json()["token"]

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


def _create_task_with_stage(admin_token, capability, task_name="orphan-test"):
    r = client.post(
        "/relay/v2/scheduler/tasks",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "task_name": task_name,
            "stages": [{"stage_name": "s1", "capability": capability}],
        },
    )
    assert r.status_code == 200, r.json()
    return r.json()["task"]["task_id"], r.json()["stages"][0]["stage_id"]


def test_fail_orphaned_stages():
    """A pending stage whose capability no node advertises is failed (unit)."""
    secret = _seed_admin()
    admin_id, admin_token = _register(
        secret, "Admin", [{"name": "admin", "version": "1.0"}], role="admin"
    )

    # No worker registers the capability "ghost.cap".
    task_id, stage_id = _create_task_with_stage(admin_token, "ghost.cap")

    result = Scheduler.fail_orphaned_stages()
    assert stage_id in result["stages_failed"]
    # Single-stage task with all stages failed → task failed.
    assert task_id in result["tasks_failed"]

    conn = get_conn()
    stage_row = conn.execute(
        "SELECT status FROM task_stages WHERE stage_id = ?", (stage_id,)
    ).fetchone()
    task_row = conn.execute(
        "SELECT status FROM tasks WHERE task_id = ?", (task_id,)
    ).fetchone()
    conn.close()
    assert stage_row["status"] == "failed"
    assert task_row["status"] == "failed"


def test_fail_orphaned_stages_keeps_known():
    """A pending stage whose capability IS advertised stays pending."""
    secret = _seed_admin()
    admin_id, admin_token = _register(
        secret, "Admin", [{"name": "admin", "version": "1.0"}], role="admin"
    )
    worker_id, worker_token = _register(
        secret,
        "Worker",
        [{"name": "known.cap", "version": "1.0"}],
        admin_token=admin_token,
    )

    task_id, stage_id = _create_task_with_stage(admin_token, "known.cap")

    result = Scheduler.fail_orphaned_stages()
    assert result == {"stages_failed": [], "tasks_failed": []}

    conn = get_conn()
    row = conn.execute(
        "SELECT status FROM task_stages WHERE stage_id = ?", (stage_id,)
    ).fetchone()
    conn.close()
    assert row["status"] == "pending"


def test_fail_orphaned_stages_ignores_offline_nodes():
    """A capability only on an offline node counts as orphaned (T-063)."""
    secret = _seed_admin()
    admin_id, admin_token = _register(
        secret, "Admin", [{"name": "admin", "version": "1.0"}], role="admin"
    )
    worker_id, worker_token = _register(
        secret,
        "Going Offline",
        [{"name": "flaky.cap", "version": "1.0"}],
        admin_token=admin_token,
    )

    # Force the worker offline.
    conn = get_conn()
    old = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    conn.execute(
        "UPDATE nodes SET status = 'offline', last_seen = ? WHERE node_id = ?",
        (old, worker_id),
    )
    # Offline node still advertises the capability, but we only count
    # approved/online nodes as covering it.
    conn.commit()
    conn.close()

    task_id, stage_id = _create_task_with_stage(admin_token, "flaky.cap")

    result = Scheduler.fail_orphaned_stages()
    assert stage_id in result["stages_failed"]


def test_fail_orphaned_stages_noop_when_clean():
    """Nothing pending → empty result."""
    secret = _seed_admin()
    admin_id, admin_token = _register(
        secret, "Admin", [{"name": "admin", "version": "1.0"}], role="admin"
    )
    result = Scheduler.fail_orphaned_stages()
    assert result == {"stages_failed": [], "tasks_failed": []}


# ---------------------------------------------------------------------------
# Integration: register_defaults wiring
# ---------------------------------------------------------------------------


def test_register_defaults_registers_all_expected_tasks():
    """The default registry wires every watchdog into the scheduler."""
    sched = MaintenanceScheduler()
    sched.register_defaults()
    names = {entry["name"] for entry in sched.status()}
    assert names == {
        "heartbeat_watchdog",
        "claim_ttl_watchdog",
        "token_cleanup",
        "artifact_cleanup",
        "chunked_upload_cleanup",
        "orphaned_stage_cleanup",
        "db_vacuum",
    }


def test_register_defaults_run_all_does_not_raise():
    """A full maintenance sweep on an empty DB is a clean no-op."""
    sched = MaintenanceScheduler()
    sched.register_defaults()
    results = sched.run_all()
    # Every registered task must have produced a result dict.
    assert set(results.keys()) == {
        "heartbeat_watchdog",
        "claim_ttl_watchdog",
        "token_cleanup",
        "artifact_cleanup",
        "chunked_upload_cleanup",
        "orphaned_stage_cleanup",
        "db_vacuum",
    }
    # No task should have raised an error.
    for name, result in results.items():
        assert "error" not in result, f"{name} errored: {result}"