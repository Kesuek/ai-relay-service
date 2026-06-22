"""Tests for the generic storage upload/download endpoints."""

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
    """Use a temporary database and artifacts dir for each test."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        settings.db_path = db_path
        settings.artifacts_dir = Path(tmp) / "artifacts"
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


def _admin_headers():
    secret = _seed_admin()
    resp = client.post(
        "/relay/v2/auth/register-admin",
        json={
            "node_name": "admin-storage-test",
            "bootstrap_secret": secret,
            "capabilities": [{"name": "admin", "version": "1.0.0"}],
        },
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_storage_upload_and_download():
    headers = _admin_headers()

    upload = client.post(
        "/relay/v2/storage/upload",
        headers=headers,
        files={"file": ("hello.txt", b"Hello Relay Storage", "text/plain")},
    )
    assert upload.status_code == 200, upload.text
    body = upload.json()
    assert body["name"] == "hello.txt"
    assert body["size_bytes"] == 19
    assert body["artifact_id"].startswith("artifact_")

    artifact_id = body["artifact_id"]

    meta = client.get(f"/relay/v2/storage/files/{artifact_id}/meta", headers=headers)
    assert meta.status_code == 200, meta.text
    assert meta.json()["name"] == "hello.txt"
    assert meta.json()["size_bytes"] == 19

    download = client.get(f"/relay/v2/storage/files/{artifact_id}", headers=headers)
    assert download.status_code == 200, download.text
    assert download.content == b"Hello Relay Storage"
    assert download.headers["content-type"].startswith("text/plain")


def test_storage_upload_rejects_oversized_file():
    headers = _admin_headers()
    original_limit = settings.max_upload_bytes
    settings.max_upload_bytes = 10
    try:
        upload = client.post(
            "/relay/v2/storage/upload",
            headers=headers,
            files={"file": ("big.bin", b"x" * 11, "application/octet-stream")},
        )
        assert upload.status_code == 413
        assert "exceeds maximum size" in upload.json()["detail"]
    finally:
        settings.max_upload_bytes = original_limit


def test_storage_upload_accepts_file_under_limit():
    headers = _admin_headers()
    original_limit = settings.max_upload_bytes
    settings.max_upload_bytes = 1024
    try:
        upload = client.post(
            "/relay/v2/storage/upload",
            headers=headers,
            files={"file": ("small.bin", b"x" * 1024, "application/octet-stream")},
        )
        assert upload.status_code == 200
        assert upload.json()["size_bytes"] == 1024
    finally:
        settings.max_upload_bytes = original_limit


def test_storage_list_and_delete():
    headers = _admin_headers()

    upload = client.post(
        "/relay/v2/storage/upload",
        headers=headers,
        files={"file": ("delete-me.bin", b"\x00\x01\x02", "application/octet-stream")},
    )
    assert upload.status_code == 200
    artifact_id = upload.json()["artifact_id"]

    listed = client.get("/relay/v2/storage/list", headers=headers)
    assert listed.status_code == 200
    ids = [a["artifact_id"] for a in listed.json()["artifacts"]]
    assert artifact_id in ids

    deleted = client.delete(f"/relay/v2/storage/files/{artifact_id}", headers=headers)
    assert deleted.status_code == 200, deleted.text

    listed = client.get("/relay/v2/storage/list", headers=headers)
    ids = [a["artifact_id"] for a in listed.json()["artifacts"]]
    assert artifact_id not in ids


def test_storage_upload_with_optional_task_stage():
    headers = _admin_headers()

    upload = client.post(
        "/relay/v2/storage/upload?task_id=task_123&stage_id=stage_456",
        headers=headers,
        files={"file": ("linked.bin", b"linked", "application/octet-stream")},
    )
    assert upload.status_code == 200, upload.text
    assert upload.json()["artifact_id"].startswith("artifact_")
