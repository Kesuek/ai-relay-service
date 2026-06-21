"""End-to-end test for upload → task → storage-node archive via relay storage router."""

import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from relay_server.config import settings
from relay_server.core.auth import (
    generate_secret,
    hash_secret,
    register_admin_node,
)
from relay_server.core.db import get_conn, init_db
from relay_server.main import app

client = TestClient(app)


def _admin_bootstrap():
    """Inject a master seed and register an admin node."""
    init_db()
    conn = get_conn()
    secret = generate_secret("adm_")
    conn.execute(
        "INSERT OR REPLACE INTO admin_seeds (seed_id, seed_hash, role, created_at) VALUES (?, ?, ?, ?)",
        ("master", hash_secret(secret), "admin", "2026-01-01T00:00:00+00:00"),
    )
    conn.commit()
    conn.close()
    r = client.post(
        "/relay/v2/auth/register-admin",
        json={
            "node_name": "admin-storage-e2e",
            "bootstrap_secret": secret,
            "capabilities": [{"name": "admin", "version": "1.0.0"}],
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _register_storage_node(admin_token, name="storage-e2e"):
    r = client.post(
        "/relay/v2/auth/register",
        json={
            "node_name": name,
            "capabilities": [
                {"name": "storage.archive", "version": "1.0.0"},
                {"name": "storage.list", "version": "1.0.0"},
            ],
            "role": "service",
        },
    )
    assert r.status_code == 200, r.text
    node_data = r.json()

    r = client.post(
        f"/relay/v2/admin/nodes/{node_data['node_id']}/approve",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "role": "service",
            "capabilities": [
                {"name": "storage.archive", "version": "1.0.0"},
                {"name": "storage.list", "version": "1.0.0"},
            ],
        },
    )
    assert r.status_code == 200, r.text
    return node_data, r.json()["token"]


@pytest.fixture(autouse=True)
def _fresh_db(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        artifacts_dir = Path(tmp) / "artifacts"
        monkeypatch.setattr(settings, "db_path", db_path)
        monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)
        init_db()
        yield


def test_storage_upload_then_archive_flow():
    admin_token = _admin_bootstrap()

    # Worker uploads a generated file
    upload = client.post(
        "/relay/v2/storage/upload",
        headers={"Authorization": f"Bearer {admin_token}"},
        files={"file": ("e2e.bin", b"\x00\x01\x02\x03", "application/octet-stream")},
    )
    assert upload.status_code == 200
    artifact = upload.json()
    assert artifact["name"] == "e2e.bin"
    assert artifact["size_bytes"] == 4

    # Storage node registers and is approved
    node_data, storage_token = _register_storage_node(admin_token)

    # Worker posts archive task
    task = client.post(
        "/relay/v2/scheduler/tasks",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "task_name": "archive_e2e_file",
            "stages": [
                {
                    "stage_name": "archive",
                    "capability": "storage.archive",
                    "payload": {
                        "artifact_id": artifact["artifact_id"],
                        "target_path": f"e2e/{artifact['artifact_id']}/e2e.bin",
                    },
                }
            ],
        },
    )
    assert task.status_code == 200
    task_id = task.json()["task"]["task_id"]

    # Storage node claims the archive stage
    claim = client.post(
        "/relay/v2/scheduler/claim",
        headers={"Authorization": f"Bearer {storage_token}"},
        json={"capability": "storage.archive"},
    )
    assert claim.status_code == 200
    stage = claim.json().get("stage")
    assert stage is not None
    assert stage["capability"] == "storage.archive"

    # Simulate writing to NAS
    payload = stage["payload"]
    artifact_id = payload["artifact_id"]
    download = client.get(
        f"/relay/v2/storage/files/{artifact_id}",
        headers={"Authorization": f"Bearer {storage_token}"},
    )
    assert download.status_code == 200
    assert download.content == b"\x00\x01\x02\x03"

    with tempfile.TemporaryDirectory() as tmp:
        nas_path = Path(tmp) / payload["target_path"]
        nas_path.parent.mkdir(parents=True, exist_ok=True)
        nas_path.write_bytes(download.content)

        complete = client.post(
            f"/relay/v2/scheduler/stages/{stage['stage_id']}/complete",
            headers={"Authorization": f"Bearer {storage_token}"},
            json={"result": {"status": "archived", "nas_path": str(nas_path)}},
        )
        assert complete.status_code == 200
        assert complete.json()["result"]["status"] == "archived"

    # Verify task status
    status = client.get(
        f"/relay/v2/scheduler/tasks/{task_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert status.status_code == 200


def test_storage_download_404_for_missing_artifact():
    admin_token = _admin_bootstrap()
    r = client.get(
        "/relay/v2/storage/files/nonexistent-id",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 404


def test_storage_meta_for_missing_artifact():
    admin_token = _admin_bootstrap()
    r = client.get(
        "/relay/v2/storage/files/nonexistent-id/meta",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 404
