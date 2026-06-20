"""Tests for the authentication and admin approval flow."""

import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ["RELAY_DB_PATH"] = ""
os.environ["RELAY_SESSION_SECRET"] = "test-session-secret-do-not-use-in-production"

from relay_server.config import settings
from relay_server.core.db import get_conn, init_db
from relay_server.main import app


@pytest.fixture(autouse=True)
def fresh_db():
    """Use a temporary database for each test."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        settings.db_path = db_path
        settings.session_secret = "test-secret"
        settings.session_cookie_secure = False
        init_db()
        yield


client = TestClient(app)


def test_health_unauthenticated():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_auth_init_master_and_register_admin():
    # The endpoint also initializes the master seed implicitly on register.
    # First call to /auth/init-master should succeed.
    r = client.post("/relay/v2/auth/init-master")
    assert r.status_code == 200
    assert r.json()["status"] == "created"

    # Second call should fail.
    r = client.post("/relay/v2/auth/init-master")
    assert r.status_code == 409


def test_register_worker_goes_pending():
    r = client.post(
        "/relay/v2/auth/register",
        json={
            "node_id": "worker-1",
            "node_name": "Worker One",
            "endpoint": "http://localhost:9001",
            "capabilities": [{"name": "board", "version": "1.0.0"}],
            "role": "service",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "pending"
    assert body["token_type"] == "temporary"
    assert body["token"].startswith("tp_")


def test_pending_cannot_access_approved_endpoints():
    r = client.post(
        "/relay/v2/auth/register",
        json={
            "node_id": "worker-2",
            "node_name": "Worker Two",
            "endpoint": "http://localhost:9001",
            "capabilities": [{"name": "board", "version": "1.0.0"}],
            "role": "service",
        },
    )
    token = r.json()["token"]

    r = client.get("/relay/v2/discovery/nodes", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200

    r = client.post("/relay/v2/scheduler/claim", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_admin_approval_flow():
    # Create master seed via CLI endpoint.
    r = client.post("/relay/v2/auth/init-master")
    assert r.status_code == 200

    # We need the secret to register admin node. Because the endpoint only
    # creates it once, we can't get the secret from the HTTP response.
    # Use core function to fetch and verify the stored hash exists.
    from relay_server.core.auth import hash_secret

    conn = get_conn()
    row = conn.execute("SELECT seed_hash FROM admin_seeds WHERE seed_id='master'").fetchone()
    assert row is not None
    # We cannot reverse the hash, so we need to call the CLI to get the secret.
    # For tests, we re-initialize the seed with a known value via the core helper
    # after deleting the row. This is acceptable because we control the fixture.
    conn.execute("DELETE FROM admin_seeds")
    conn.commit()
    conn.close()

    from relay_server.core.auth import generate_secret

    secret = generate_secret("adm_")
    conn = get_conn()
    conn.execute(
        "INSERT INTO admin_seeds (seed_id, seed_hash, role, created_at) VALUES (?, ?, ?, ?)",
        ("master", hash_secret(secret), "admin", "2026-01-01T00:00:00+00:00"),
    )
    conn.commit()
    conn.close()

    # Register admin node with known secret.
    r = client.post(
        "/relay/v2/auth/register",
        json={
            "node_id": "admin-dashboard",
            "node_name": "Admin Dashboard",
            "bootstrap_secret": secret,
            "capabilities": [{"name": "admin", "version": "1.0.0"}],
            "role": "admin",
        },
    )
    assert r.status_code == 200
    admin_token = r.json()["token"]

    # Register worker node pending.
    r = client.post(
        "/relay/v2/auth/register",
        json={
            "node_id": "worker-3",
            "node_name": "Worker Three",
            "endpoint": "http://localhost:9001",
            "capabilities": [{"name": "board", "version": "1.0.0"}],
            "role": "service",
        },
    )
    assert r.status_code == 200
    worker_pending_token = r.json()["token"]

    # Pending worker cannot list admin nodes.
    r = client.get(
        "/relay/v2/admin/nodes", headers={"Authorization": f"Bearer {worker_pending_token}"}
    )
    assert r.status_code in (401, 403)

    # Admin approves worker.
    r = client.post(
        "/relay/v2/admin/nodes/worker-3/approve",
        json={"role": "service", "capabilities": [{"name": "board", "version": "1.0.0"}]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    worker_token = r.json()["token"]
    assert worker_token.startswith("rt_")

    # Approved worker can access scheduler endpoint.
    r = client.post(
        "/relay/v2/scheduler/claim", headers={"Authorization": f"Bearer {worker_token}"}
    )
    assert r.status_code == 200


def test_refresh_token():
    from relay_server.core.auth import generate_secret, hash_secret

    conn = get_conn()
    secret = generate_secret("adm_")
    conn.execute(
        "INSERT INTO admin_seeds (seed_id, seed_hash, role, created_at) VALUES (?, ?, ?, ?)",
        ("master", hash_secret(secret), "admin", "2026-01-01T00:00:00+00:00"),
    )
    conn.commit()
    conn.close()

    r = client.post(
        "/relay/v2/auth/register",
        json={
            "node_id": "admin-refresh",
            "node_name": "Admin Refresh",
            "bootstrap_secret": secret,
            "capabilities": [{"name": "admin", "version": "1.0.0"}],
            "role": "admin",
        },
    )
    token = r.json()["token"]

    r = client.post("/relay/v2/auth/refresh", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    new_token = r.json()["token"]
    assert new_token != token

    # Old token invalidated.
    r = client.get("/relay/v2/admin/nodes", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401

    # New token works.
    r = client.get("/relay/v2/admin/nodes", headers={"Authorization": f"Bearer {new_token}"})
    assert r.status_code == 200


def test_human_admin_user_can_approve_and_issue_token():
    """A human user in the admin group can approve nodes and issue tokens."""
    from relay_server.core.users import create_user

    init_db()

    # Create a human admin user.
    create_user(username="admin-human", password="secret123", group_names=["admin"])

    # Log in to obtain session cookies.
    r = client.post(
        "/relay/v2/dashboard/login",
        data={"mode": "user", "username": "admin-human", "password": "secret123"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    cookies = r.cookies

    # Register a pending worker node.
    r = client.post(
        "/relay/v2/auth/register",
        json={
            "node_id": "worker-human-admin",
            "node_name": "Worker Human Admin",
            "endpoint": "http://localhost:9001",
            "capabilities": [{"name": "board", "version": "1.0.0"}],
            "role": "service",
        },
    )
    assert r.status_code == 200

    # Admin human can list nodes.
    r = client.get("/relay/v2/admin/nodes", cookies=cookies)
    assert r.status_code == 200
    node_ids = [n["node_id"] for n in r.json()["nodes"]]
    assert "worker-human-admin" in node_ids

    # Admin human can approve the node.
    r = client.post(
        "/relay/v2/admin/nodes/worker-human-admin/approve",
        json={"role": "service", "capabilities": [{"name": "board", "version": "1.0.0"}]},
        cookies=cookies,
    )
    assert r.status_code == 200
    worker_token = r.json()["token"]
    assert worker_token.startswith("rt_")

    # Admin human can issue a new runtime token.
    r = client.post("/relay/v2/admin/nodes/worker-human-admin/token", cookies=cookies)
    assert r.status_code == 200
    assert r.json()["token"].startswith("rt_")


def test_human_user_without_permission_gets_403():
    """A human user without the required permissions is denied access."""
    from relay_server.core.users import create_user

    init_db()

    # Create a human viewer user (dashboard:view only).
    create_user(username="viewer-human", password="secret123", group_names=["viewer"])

    # Log in to obtain session cookies.
    r = client.post(
        "/relay/v2/dashboard/login",
        data={"mode": "user", "username": "viewer-human", "password": "secret123"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    cookies = r.cookies

    # Register a pending worker node.
    r = client.post(
        "/relay/v2/auth/register",
        json={
            "node_id": "worker-viewer",
            "node_name": "Worker Viewer",
            "endpoint": "http://localhost:9001",
            "capabilities": [{"name": "board", "version": "1.0.0"}],
            "role": "service",
        },
    )
    assert r.status_code == 200

    # Viewer can list nodes (dashboard:view).
    r = client.get("/relay/v2/admin/nodes", cookies=cookies)
    assert r.status_code == 200

    # Viewer cannot approve nodes.
    r = client.post(
        "/relay/v2/admin/nodes/worker-viewer/approve",
        json={"role": "service", "capabilities": [{"name": "board", "version": "1.0.0"}]},
        cookies=cookies,
    )
    assert r.status_code == 403

    # Viewer cannot issue tokens.
    r = client.post("/relay/v2/admin/nodes/worker-viewer/token", cookies=cookies)
    assert r.status_code == 403


def test_human_user_with_explicit_node_permissions():
    """A non-admin human user with explicit nodes:approve/token permissions can use them."""
    from relay_server.core.users import create_user, set_group_permissions
    from relay_server.core.db import get_conn

    init_db()

    conn = get_conn()
    conn.execute(
        "INSERT INTO groups (group_id, group_name, description, created_at) VALUES (?, ?, ?, ?)",
        ("grp_nodemgr", "nodemgr", "Node managers", "2026-01-01T00:00:00+00:00"),
    )
    conn.commit()
    conn.close()

    # Assign explicit node permissions to the custom group.
    set_group_permissions("grp_nodemgr", ["nodes:approve", "nodes:token"])

    create_user(username="node-manager", password="secret123", group_names=["nodemgr"])

    r = client.post(
        "/relay/v2/dashboard/login",
        data={"mode": "user", "username": "node-manager", "password": "secret123"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    cookies = r.cookies

    # Register and approve a node.
    r = client.post(
        "/relay/v2/auth/register",
        json={
            "node_id": "worker-nodemgr",
            "node_name": "Worker Node Manager",
            "endpoint": "http://localhost:9001",
            "capabilities": [{"name": "board", "version": "1.0.0"}],
            "role": "service",
        },
    )
    assert r.status_code == 200

    # Node manager can approve (nodes:approve).
    r = client.post(
        "/relay/v2/admin/nodes/worker-nodemgr/approve",
        json={"role": "service", "capabilities": [{"name": "board", "version": "1.0.0"}]},
        cookies=cookies,
    )
    assert r.status_code == 200

    # Node manager can issue token (nodes:token).
    r = client.post("/relay/v2/admin/nodes/worker-nodemgr/token", cookies=cookies)
    assert r.status_code == 200

    # But cannot list nodes (missing dashboard:view).
    r = client.get("/relay/v2/admin/nodes", cookies=cookies)
    assert r.status_code == 403
