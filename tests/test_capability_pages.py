"""Tests for capability dashboard pages (T-048).

Covers:
  - GET /relay/v2/capabilities/<name>/dashboard-page — 404 when absent,
    HTML when present.
  - POST /relay/v2/storage/upload?capability=<name> — file is stored as
    ``<capability_pages_dir>/<name>/dashboard.html`` and no artifact DB
    entry is created.
  - Path-traversal protection on the capability name.
"""

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
def fresh_db_and_pages():
    """Use a temporary DB, artifacts dir, and capability-pages dir per test."""
    with tempfile.TemporaryDirectory() as tmp:
        settings.db_path = Path(tmp) / "test.db"
        settings.session_secret = "test-session-secret-do-not-use-in-production"
        settings.artifacts_dir = Path(tmp) / "artifacts"
        settings.chunked_uploads_dir = Path(tmp) / "chunked_uploads"
        settings.capability_pages_dir = Path(tmp) / "capability-pages"
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
            "node_name": "admin-cap-pages-test",
            "bootstrap_secret": secret,
            "capabilities": [{"name": "admin", "version": "1.0.0"}],
        },
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["token"]
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# GET /relay/v2/capabilities/<name>/dashboard-page
# ---------------------------------------------------------------------------

def test_dashboard_page_not_found():
    resp = client.get("/relay/v2/capabilities/nonexistent/dashboard-page")
    assert resp.status_code == 404


def test_dashboard_page_served():
    page_dir = settings.capability_pages_dir / "test-cap"
    page_dir.mkdir(parents=True)
    (page_dir / "dashboard.html").write_text(
        "<html><body><h1>Test</h1></body></html>", encoding="utf-8"
    )
    resp = client.get("/relay/v2/capabilities/test-cap/dashboard-page")
    assert resp.status_code == 200
    assert b"<h1>Test</h1>" in resp.content
    assert resp.headers["content-type"].startswith("text/html")
    # Must be embeddable in a same-origin iframe.
    assert resp.headers["x-frame-options"] == "SAMEORIGIN"


def test_dashboard_page_rejects_path_traversal():
    # Path separators are normalised by the router and never reach the
    # handler as part of <name>, so the traversal guard fires for the
    # dot-segment forms that survive routing.
    resp = client.get("/relay/v2/capabilities/%2e%2e/dashboard-page")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /relay/v2/storage/upload?capability=<name>
# ---------------------------------------------------------------------------

def test_upload_capability_dashboard_page():
    headers = _admin_headers()
    html = b"<html><body><h1>Cap Dashboard</h1></body></html>"
    resp = client.post(
        "/relay/v2/storage/upload?capability=image.generate.mflux",
        headers=headers,
        files={"file": ("dashboard.html", html, "text/html")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    assert body["path"] == "capability-pages/image.generate.mflux/dashboard.html"
    assert body["capability"] == "image.generate.mflux"
    assert body["size_bytes"] == len(html)

    # File exists at the expected path.
    page = settings.capability_pages_dir / "image.generate.mflux" / "dashboard.html"
    assert page.is_file()
    assert page.read_bytes() == html

    # Now served by the dashboard-page endpoint.
    served = client.get("/relay/v2/capabilities/image.generate.mflux/dashboard-page")
    assert served.status_code == 200
    assert b"<h1>Cap Dashboard</h1>" in served.content


def test_upload_capability_overwrites_existing_page():
    headers = _admin_headers()
    page = settings.capability_pages_dir / "overwrite-cap" / "dashboard.html"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_bytes(b"<old/>")

    client.post(
        "/relay/v2/storage/upload?capability=overwrite-cap",
        headers=headers,
        files={"file": ("dashboard.html", b"<new/>", "text/html")},
    )
    assert page.read_bytes() == b"<new/>"


def test_upload_capability_rejects_path_traversal():
    headers = _admin_headers()
    resp = client.post(
        "/relay/v2/storage/upload?capability=../escape",
        headers=headers,
        files={"file": ("dashboard.html", b"x", "text/html")},
    )
    assert resp.status_code == 400


def test_upload_capability_does_not_create_artifact():
    headers = _admin_headers()
    client.post(
        "/relay/v2/storage/upload?capability=artifact-check-cap",
        headers=headers,
        files={"file": ("dashboard.html", b"<x/>", "text/html")},
    )
    # The artifact list must be empty — no artifact DB entry was created.
    listing = client.get("/relay/v2/storage/list", headers=headers)
    assert listing.status_code == 200, listing.text
    assert listing.json()["artifacts"] == []