"""Tests for the generic storage upload/download endpoints."""

import base64
import os
import tempfile
from pathlib import Path

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
    """Use a temporary database and artifacts dir for each test."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        settings.db_path = db_path
        settings.session_secret = "test-session-secret-do-not-use-in-production"
        settings.artifacts_dir = Path(tmp) / "artifacts"
        settings.chunked_uploads_dir = Path(tmp) / "chunked_uploads"
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


def test_storage_large_upload_exceeds_spool_ram_threshold():
    """Upload a file larger than the SpooledTemporaryFile RAM threshold (1 MiB).

    Forces the spool to roll over to disk and exercises the chunkwise move
    path in store_artifact_from_file.
    """
    headers = _admin_headers()
    content = b"x" * (2 * 1024 * 1024)  # 2 MiB -> spills past the 1 MiB spool

    upload = client.post(
        "/relay/v2/storage/upload",
        headers=headers,
        files={"file": ("large.bin", content, "application/octet-stream")},
    )
    assert upload.status_code == 200, upload.text
    body = upload.json()
    assert body["name"] == "large.bin"
    assert body["size_bytes"] == len(content)

    artifact_id = body["artifact_id"]

    download = client.get(f"/relay/v2/storage/files/{artifact_id}", headers=headers)
    assert download.status_code == 200
    assert download.content == content


def test_storage_upload_with_optional_task_stage():
    headers = _admin_headers()

    upload = client.post(
        "/relay/v2/storage/upload?task_id=task_123&stage_id=stage_456",
        headers=headers,
        files={"file": ("linked.bin", b"linked", "application/octet-stream")},
    )
    assert upload.status_code == 200, upload.text
    assert upload.json()["artifact_id"].startswith("artifact_")


# ── Chunked upload tests ────────────────────────────────────────


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def test_chunked_upload_happy_path():
    headers = _admin_headers()
    chunks = [b"AAA", b"BBB", b"CCC"]
    expected = b"".join(chunks)

    init = client.post(
        "/relay/v2/storage/chunked/init",
        headers=headers,
        json={"name": "test.bin", "mime_type": "application/octet-stream", "total_chunks": 3},
    )
    assert init.status_code == 200, init.text
    upload_id = init.json()["upload_id"]
    assert init.json()["status"] == "init"
    assert upload_id.startswith("upl_")

    for i, chunk in enumerate(chunks):
        r = client.post(
            f"/relay/v2/storage/chunked/{upload_id}/chunk",
            headers=headers,
            json={"chunk_index": i, "data_b64": _b64(chunk)},
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "received"
        assert r.json()["received"] == i + 1

    complete = client.post(
        f"/relay/v2/storage/chunked/{upload_id}/complete",
        headers=headers,
        json={},
    )
    assert complete.status_code == 200, complete.text
    body = complete.json()
    assert body["status"] == "created"
    assert body["size_bytes"] == len(expected)
    artifact_id = body["artifact_id"]

    download = client.get(f"/relay/v2/storage/files/{artifact_id}", headers=headers)
    assert download.status_code == 200
    assert download.content == expected


def test_chunked_upload_complete_missing_chunks():
    headers = _admin_headers()

    init = client.post(
        "/relay/v2/storage/chunked/init",
        headers=headers,
        json={"name": "partial.bin", "total_chunks": 3},
    )
    upload_id = init.json()["upload_id"]

    # Only upload chunk 0
    client.post(
        f"/relay/v2/storage/chunked/{upload_id}/chunk",
        headers=headers,
        json={"chunk_index": 0, "data_b64": _b64(b"AAA")},
    )

    complete = client.post(
        f"/relay/v2/storage/chunked/{upload_id}/complete",
        headers=headers,
        json={},
    )
    assert complete.status_code == 400
    assert "Missing chunks" in complete.json()["detail"]


def test_chunked_upload_chunk_for_unknown_session():
    headers = _admin_headers()
    r = client.post(
        "/relay/v2/storage/chunked/upl_doesnotexist/chunk",
        headers=headers,
        json={"chunk_index": 0, "data_b64": _b64(b"x")},
    )
    assert r.status_code == 404


def test_chunked_upload_checksum_mismatch():
    import hashlib

    headers = _admin_headers()
    payload = b"hello-chunked-world"
    chunks = [payload[:5], payload[5:11], payload[11:]]

    init = client.post(
        "/relay/v2/storage/chunked/init",
        headers=headers,
        json={"name": "chk.bin", "total_chunks": len(chunks)},
    )
    upload_id = init.json()["upload_id"]

    for i, chunk in enumerate(chunks):
        client.post(
            f"/relay/v2/storage/chunked/{upload_id}/chunk",
            headers=headers,
            json={"chunk_index": i, "data_b64": _b64(chunk)},
        )

    wrong = "0" * 64
    complete = client.post(
        f"/relay/v2/storage/chunked/{upload_id}/complete",
        headers=headers,
        json={"checksum": wrong},
    )
    assert complete.status_code == 400
    assert "Checksum mismatch" in complete.json()["detail"]

    # The session should still be present so the client can retry/inspect.
    # A correct checksum must now succeed.
    correct = hashlib.sha256(payload).hexdigest()
    complete2 = client.post(
        f"/relay/v2/storage/chunked/{upload_id}/complete",
        headers=headers,
        json={"checksum": correct},
    )
    assert complete2.status_code == 200, complete2.text
    assert complete2.json()["status"] == "created"


def test_chunked_upload_rejects_bad_base64():
    headers = _admin_headers()
    init = client.post(
        "/relay/v2/storage/chunked/init",
        headers=headers,
        json={"name": "bad.bin", "total_chunks": 1},
    )
    upload_id = init.json()["upload_id"]
    r = client.post(
        f"/relay/v2/storage/chunked/{upload_id}/chunk",
        headers=headers,
        json={"chunk_index": 0, "data_b64": "!!!not base64!!!"},
    )
    assert r.status_code == 400
    assert "base64" in r.json()["detail"]


def test_chunked_upload_rejects_chunk_index_out_of_range():
    headers = _admin_headers()
    init = client.post(
        "/relay/v2/storage/chunked/init",
        headers=headers,
        json={"name": "oor.bin", "total_chunks": 2},
    )
    upload_id = init.json()["upload_id"]
    r = client.post(
        f"/relay/v2/storage/chunked/{upload_id}/chunk",
        headers=headers,
        json={"chunk_index": 5, "data_b64": _b64(b"x")},
    )
    assert r.status_code == 400
    assert "out of range" in r.json()["detail"]
