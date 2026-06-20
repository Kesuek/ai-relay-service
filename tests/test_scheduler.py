"""Tests for scheduler task lifecycle."""

import os
import tempfile
from pathlib import Path
from typing import Optional

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
        settings.heartbeat_interval_seconds = 10
        settings.heartbeat_timeout_multiplier = 2
        settings.claim_ttl_seconds = 60
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


def _register(
    secret: str, node_id: str, caps: list, role: str = "service", admin_token: Optional[str] = None
) -> str:
    if role == "admin":
        r = client.post(
            "/relay/v2/auth/register",
            json={
                "node_id": node_id,
                "node_name": node_id,
                "bootstrap_secret": secret,
                "capabilities": caps,
                "role": role,
            },
        )
        assert r.status_code == 200, r.json()
        return r.json()["token"]

    r = client.post(
        "/relay/v2/auth/register",
        json={
            "node_id": node_id,
            "node_name": node_id,
            "endpoint": "http://localhost:9001",
            "capabilities": caps,
            "role": role,
        },
    )
    assert r.status_code == 200, r.json()

    approval_token = admin_token or _admin_token(secret)
    r2 = client.post(
        f"/relay/v2/admin/nodes/{node_id}/approve",
        headers={"Authorization": f"Bearer {approval_token}"},
        json={"role": role, "capabilities": caps},
    )
    assert r2.status_code == 200, r2.json()
    return r2.json()["token"]


def _admin_token(secret: str) -> str:
    r = client.post(
        "/relay/v2/auth/register",
        json={
            "node_id": "admin-test",
            "node_name": "admin-test",
            "bootstrap_secret": secret,
            "capabilities": [{"name": "admin", "version": "1.0.0"}],
            "role": "admin",
        },
    )
    assert r.status_code == 200
    return r.json()["token"]


def test_create_task_and_view():
    secret = _seed_admin()
    admin_token = _register(secret, "admin", [{"name": "admin", "version": "1.0"}], "admin")

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
    admin_token = _register(secret, "admin", [{"name": "admin", "version": "1.0"}], "admin")
    web_token = _register(
        secret, "web-node", [{"name": "web_fetch", "version": "1.0"}], admin_token=admin_token
    )
    llm_token = _register(
        secret, "llm-node", [{"name": "llm", "version": "1.0"}], admin_token=admin_token
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
    assert r.json()["stage"]["claimed_by"] == "web-node"

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
    admin_token = _register(secret, "admin", [{"name": "admin", "version": "1.0"}], "admin")
    web_token = _register(
        secret, "web-node", [{"name": "web_fetch", "version": "1.0"}], admin_token=admin_token
    )
    other_token = _register(
        secret, "other-node", [{"name": "web_fetch", "version": "1.0"}], admin_token=admin_token
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
    admin_token = _register(secret, "admin", [{"name": "admin", "version": "1.0"}], "admin")

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
    assert body["created_by"] == "admin"

    r = client.get(
        f"/relay/v2/scheduler/artifacts/{task_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    assert len(r.json()["artifacts"]) == 1
    assert r.json()["artifacts"][0]["size_bytes"] == 11
