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
        settings.session_secret = "test-session-secret-do-not-use-in-production"
        settings.session_cookie_secure = False
        # Reset cached pepper so each test re-evaluates session_secret.
        import relay_server.core.auth as auth_mod

        auth_mod._TOKEN_PEPPER = None
        init_db()
        yield
        auth_mod._TOKEN_PEPPER = None


client = TestClient(app)


def test_health_unauthenticated():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_auth_init_master_and_register_admin():
    # Master seed must be initialized via CLI. API endpoint was removed for
    # security, so we bootstrap directly from the core function in tests.
    from relay_server.core.auth import init_master_seed, secret_entropy_bits

    seed = init_master_seed()
    assert seed is not None
    assert seed.startswith("adm_")

    # The seed should have high entropy (256 bits generated, minus prefix overhead).
    assert secret_entropy_bits(seed) >= 200

    # Verify the stored hash is NOT the plaintext seed and uses salted format.
    from relay_server.core.db import get_conn

    conn = get_conn()
    row = conn.execute(
        "SELECT seed_hash FROM admin_seeds WHERE seed_id = ?", ("master",)
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["seed_hash"] != seed
    assert row["seed_hash"].startswith(("$2a$", "$2b$", "$2y$"))

    # Admin node registration uses the master seed.
    r = client.post(
        "/relay/v2/auth/register-admin",
        json={
            "node_name": "Admin Bot",
            "bootstrap_secret": seed,
            "endpoint": None,
            "capabilities": [{"name": "admin", "version": "1.0.0"}],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "approved"
    assert body["token_type"] == "runtime"
    assert body["token"].startswith("rt_")

    # init_master_seed is idempotent and returns None after the first call.
    assert init_master_seed() is None


def test_register_worker_goes_pending():
    r = client.post(
        "/relay/v2/auth/register",
        json={
            "node_name": "Worker One",
            "endpoint": "http://localhost:9001",
            "capabilities": [{"name": "board", "version": "1.0.0"}],
            "role": "service",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["node_id"]) == 8
    assert body["status"] == "pending"
    assert body["token_type"] == "temporary"
    assert body["token"].startswith("tp_")


def test_pending_cannot_access_approved_endpoints():
    r = client.post(
        "/relay/v2/auth/register",
        json={
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


def _register_worker(name: str, caps: list) -> tuple[str, str, str]:
    r = client.post(
        "/relay/v2/auth/register",
        json={
            "node_name": name,
            "endpoint": "http://localhost:9001",
            "capabilities": caps,
            "role": "service",
        },
    )
    assert r.status_code == 200
    body = r.json()
    return body["node_id"], body["token"], body["registration_secret"]


def test_admin_approval_flow():
    # Create master seed via CLI/bootstrap function (API endpoint removed).
    from relay_server.core.auth import hash_secret

    conn = get_conn()
    row = conn.execute("SELECT seed_hash FROM admin_seeds WHERE seed_id='master'").fetchone()
    if row is None:
        from relay_server.core.auth import init_master_seed
        secret = init_master_seed()
        assert secret is not None
    else:
        # For tests, re-initialize with a known secret.
        conn.execute("DELETE FROM admin_seeds")
        conn.commit()
        from relay_server.core.auth import generate_secret
        secret = generate_secret("adm_")
        conn.execute(
            "INSERT INTO admin_seeds (seed_id, seed_hash, role, created_at) VALUES (?, ?, ?, ?)",
            ("master", hash_secret(secret), "admin", "2026-01-01T00:00:00+00:00"),
        )
        conn.commit()
    conn.close()

    # Register admin node with known secret.
    admin_id, admin_token = _register_admin(secret)

    # Register worker node pending.
    worker_id, worker_pending_token, _ = _register_worker(
        "Worker Three", [{"name": "board", "version": "1.0.0"}]
    )

    # Pending worker cannot list admin nodes.
    r = client.get(
        "/relay/v2/admin/nodes", headers={"Authorization": f"Bearer {worker_pending_token}"}
    )
    assert r.status_code in (401, 403)

    # Admin approves worker.
    r = client.post(
        f"/relay/v2/admin/nodes/{worker_id}/approve",
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
        "/relay/v2/auth/register-admin",
        json={
            "node_name": "Admin Refresh",
            "bootstrap_secret": secret,
            "capabilities": [{"name": "admin", "version": "1.0.0"}],
        },
    )
    admin_token = r.json()["token"]

    worker_id, _, rs = _register_worker(
        "Worker Refresh", [{"name": "board", "version": "1.0.0"}]
    )

    # Pending worker can poll status with registration secret.
    r = client.post(
        "/relay/v2/auth/status",
        json={"node_id": worker_id, "registration_secret": rs},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "pending"
    assert body["rt_valid_until"] is None
    assert body["rs_valid_until"] is not None

    # Approve worker.
    r = client.post(
        f"/relay/v2/admin/nodes/{worker_id}/approve",
        json={"role": "service", "capabilities": [{"name": "board", "version": "1.0.0"}]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    worker_token = r.json()["token"]
    assert worker_token.startswith("rt_")

    # Approved worker can poll status with runtime token.
    r = client.post(
        "/relay/v2/auth/status",
        headers={"Authorization": f"Bearer {worker_token}"},
        json={"node_id": worker_id},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "approved"

    # Refresh runtime token with runtime token.
    r = client.post(
        "/relay/v2/auth/refresh",
        headers={"Authorization": f"Bearer {worker_token}"},
        json={"requested_credential": "runtime_token"},
    )
    assert r.status_code == 200
    new_token = r.json()["token"]
    assert new_token != worker_token

    # Old runtime token invalidated.
    r = client.post(
        "/relay/v2/scheduler/claim",
        headers={"Authorization": f"Bearer {worker_token}"},
    )
    assert r.status_code == 401

    # New token works.
    r = client.post(
        "/relay/v2/scheduler/claim",
        headers={"Authorization": f"Bearer {new_token}"},
    )
    assert r.status_code == 200

    # Recover runtime token with registration secret (rs gets rotated).
    r = client.post(
        "/relay/v2/auth/refresh",
        json={
            "node_id": worker_id,
            "requested_credential": "runtime_token",
            "registration_secret": rs,
        },
    )
    assert r.status_code == 200
    recovered_token = r.json()["token"]
    assert recovered_token != new_token

    # Recovered token works.
    r = client.post(
        "/relay/v2/scheduler/claim",
        headers={"Authorization": f"Bearer {recovered_token}"},
    )
    assert r.status_code == 200


def test_online_node_token_still_valid():
    """After heartbeats move a node to 'online', its runtime token stays valid."""
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
        "/relay/v2/auth/register-admin",
        json={
            "node_name": "Admin Online",
            "bootstrap_secret": secret,
            "capabilities": [{"name": "admin", "version": "1.0.0"}],
        },
    )
    assert r.status_code == 200
    admin_token = r.json()["token"]

    worker_id, _, _ = _register_worker(
        "Worker Online", [{"name": "board", "version": "1.0.0"}]
    )
    r = client.post(
        f"/relay/v2/admin/nodes/{worker_id}/approve",
        json={"role": "service", "capabilities": [{"name": "board", "version": "1.0.0"}]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    worker_token = r.json()["token"]

    # Heartbeat moves node to online.
    r = client.post(
        "/relay/v2/discovery/heartbeat",
        headers={"Authorization": f"Bearer {worker_token}"},
        json={"capabilities": [{"name": "board", "version": "1.0.0"}], "status": "idle"},
    )
    assert r.status_code == 200

    # Token still works for scheduler claim.
    r = client.post(
        "/relay/v2/scheduler/claim",
        headers={"Authorization": f"Bearer {worker_token}"},
    )
    assert r.status_code == 200


def test_human_admin_user_can_approve_and_issue_token():
    """A human user in the admin group can approve nodes and issue tokens."""
    from relay_server.core.users import create_user

    init_db()

    # Create a human admin user.
    create_user(
        username="admin-human", password="very-secret-password-99",
        group_names=["admin"], force_password_change=False,
    )

    # Log in to obtain session cookies.
    r = client.post(
        "/relay/v2/dashboard/login",
        data={"mode": "user", "username": "admin-human", "password": "very-secret-password-99"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    cookies = r.cookies

    # Register a pending worker node.
    worker_id, _, _ = _register_worker(
        "Worker Human Admin", [{"name": "board", "version": "1.0.0"}]
    )

    # Admin human can list nodes.
    r = client.get("/relay/v2/admin/nodes", cookies=cookies)
    assert r.status_code == 200
    node_ids = [n["node_id"] for n in r.json()["nodes"]]
    assert worker_id in node_ids

    # Admin human can approve the node.
    r = client.post(
        f"/relay/v2/admin/nodes/{worker_id}/approve",
        json={"role": "service", "capabilities": [{"name": "board", "version": "1.0.0"}]},
        cookies=cookies,
    )
    assert r.status_code == 200
    worker_token = r.json()["token"]
    assert worker_token.startswith("rt_")

    # Admin human can issue a new runtime token.
    r = client.post(f"/relay/v2/admin/nodes/{worker_id}/token", cookies=cookies)
    assert r.status_code == 200
    assert r.json()["token"].startswith("rt_")


def test_human_user_without_permission_gets_403():
    """A human user without the required permissions is denied access."""
    from relay_server.core.users import create_user

    init_db()

    # Create a human viewer user (dashboard:view only).
    create_user(
        username="viewer-human", password="very-secret-password-99",
        group_names=["viewer"], force_password_change=False,
    )

    # Log in to obtain session cookies.
    r = client.post(
        "/relay/v2/dashboard/login",
        data={"mode": "user", "username": "viewer-human", "password": "very-secret-password-99"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    cookies = r.cookies

    # Register a pending worker node.
    worker_id, _, _ = _register_worker(
        "Worker Viewer", [{"name": "board", "version": "1.0.0"}]
    )

    # Viewer can list nodes (dashboard:view).
    r = client.get("/relay/v2/admin/nodes", cookies=cookies)
    assert r.status_code == 200

    # Viewer cannot approve nodes.
    r = client.post(
        f"/relay/v2/admin/nodes/{worker_id}/approve",
        json={"role": "service", "capabilities": [{"name": "board", "version": "1.0.0"}]},
        cookies=cookies,
    )
    assert r.status_code == 403

    # Viewer cannot issue tokens.
    r = client.post(f"/relay/v2/admin/nodes/{worker_id}/token", cookies=cookies)
    assert r.status_code == 403


def test_human_user_with_explicit_node_permissions():
    """A non-admin human user with explicit nodes:approve/token permissions can use them."""
    from relay_server.core.db import get_conn
    from relay_server.core.users import create_user, set_group_permissions

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

    create_user(
        username="node-manager", password="very-secret-password-99",
        group_names=["nodemgr"], force_password_change=False,
    )

    r = client.post(
        "/relay/v2/dashboard/login",
        data={"mode": "user", "username": "node-manager", "password": "very-secret-password-99"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    cookies = r.cookies

    # Register and approve a node.
    worker_id, _, _ = _register_worker(
        "Worker Node Manager", [{"name": "board", "version": "1.0.0"}]
    )

    # Node manager can approve (nodes:approve).
    r = client.post(
        f"/relay/v2/admin/nodes/{worker_id}/approve",
        json={"role": "service", "capabilities": [{"name": "board", "version": "1.0.0"}]},
        cookies=cookies,
    )
    assert r.status_code == 200

    # Node manager can issue token (nodes:token).
    r = client.post(f"/relay/v2/admin/nodes/{worker_id}/token", cookies=cookies)
    assert r.status_code == 200

    # But cannot list nodes (missing dashboard:view).
    r = client.get("/relay/v2/admin/nodes", cookies=cookies)
    assert r.status_code == 403



def test_status_is_read_only_and_reports_cred_lifetimes():
    """/auth/status with a runtime token returns TTLs without rotating anything."""
    from relay_server.core.auth import approve_node, register_pending_node

    init_db()

    node_id, _, _ = register_pending_node(
        node_name="Status Reporter",
        endpoint="http://status.local",
        capabilities=[{"name": "board", "version": "1.0.0"}],
        role="service",
    )
    runtime_token = approve_node(node_id, role="service")
    assert runtime_token is not None

    r = client.post(
        "/relay/v2/auth/status",
        headers={"Authorization": f"Bearer {runtime_token}"},
        json={"node_id": node_id},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["node_id"] == node_id
    assert body["rt_valid_until"] is not None
    assert body["rs_valid_until"] is not None

    # Same token still works after /auth/status.
    r = client.get(
        "/relay/v2/discovery/nodes", headers={"Authorization": f"Bearer {runtime_token}"}
    )
    assert r.status_code == 200


def test_refresh_runtime_token_rotates_it():
    """Refreshing the runtime token invalidates the old one."""
    from relay_server.core.auth import approve_node, register_pending_node

    init_db()

    node_id, _, _ = register_pending_node(
        node_name="Refresh Runner",
        endpoint="http://refresh.local",
        capabilities=[{"name": "board", "version": "1.0.0"}],
        role="service",
    )
    runtime_token = approve_node(node_id, role="service")

    r = client.post(
        "/relay/v2/auth/refresh",
        headers={"Authorization": f"Bearer {runtime_token}"},
        json={"requested_credential": "runtime_token"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "runtime"
    new_token = body["token"]
    assert new_token != runtime_token
    assert new_token.startswith("rt_")

    # Old token invalidated.
    r = client.get(
        "/relay/v2/discovery/nodes", headers={"Authorization": f"Bearer {runtime_token}"}
    )
    assert r.status_code == 401

    # New token works.
    r = client.get(
        "/relay/v2/discovery/nodes", headers={"Authorization": f"Bearer {new_token}"}
    )
    assert r.status_code == 200


def test_refresh_registration_secret_with_runtime_token():
    """A valid runtime token can proactively rotate the registration secret."""
    from relay_server.core.auth import approve_node, register_pending_node

    init_db()

    node_id, _, reg_secret = register_pending_node(
        node_name="RS Rotator",
        endpoint="http://rs.local",
        capabilities=[{"name": "board", "version": "1.0.0"}],
        role="service",
    )
    runtime_token = approve_node(node_id, role="service")

    r = client.post(
        "/relay/v2/auth/refresh",
        headers={"Authorization": f"Bearer {runtime_token}"},
        json={"requested_credential": "registration_secret"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "registration_secret"
    new_secret = body["token"]
    assert new_secret.startswith("rs_")
    assert new_secret != reg_secret

    # Old registration secret no longer works for recovery.
    r = client.post(
        "/relay/v2/auth/refresh",
        json={
            "node_id": node_id,
            "requested_credential": "runtime_token",
            "registration_secret": reg_secret,
        },
    )
    assert r.status_code == 401

    # New registration secret recovers a runtime token.
    r = client.post(
        "/relay/v2/auth/refresh",
        json={
            "node_id": node_id,
            "requested_credential": "runtime_token",
            "registration_secret": new_secret,
        },
    )
    assert r.status_code == 200
    recovered_token = r.json()["token"]
    assert recovered_token.startswith("rt_")

    # The runtime token used before recovery is invalidated.
    r = client.get(
        "/relay/v2/discovery/nodes", headers={"Authorization": f"Bearer {runtime_token}"}
    )
    assert r.status_code == 401

    # Recovered token works.
    r = client.get(
        "/relay/v2/discovery/nodes", headers={"Authorization": f"Bearer {recovered_token}"}
    )
    assert r.status_code == 200


def test_expired_registration_secret_cannot_recover_runtime_token():
    """When the registration secret expires, recovery is impossible."""
    from relay_server.core.auth import approve_node, register_pending_node
    from relay_server.core.db import get_conn

    init_db()

    node_id, _, reg_secret = register_pending_node(
        node_name="Expired RS",
        endpoint="http://expired.local",
        capabilities=[{"name": "board", "version": "1.0.0"}],
        role="service",
    )
    _runtime_token = approve_node(node_id, role="service")

    # Artificially expire the registration secret in the database.
    conn = get_conn()
    conn.execute(
        "UPDATE nodes SET registration_secret_expires_at = ? WHERE node_id = ?",
        ("2020-01-01T00:00:00+00:00", node_id),
    )
    conn.commit()
    conn.close()

    r = client.post(
        "/relay/v2/auth/refresh",
        json={
            "node_id": node_id,
            "requested_credential": "runtime_token",
            "registration_secret": reg_secret,
        },
    )
    assert r.status_code == 401


def test_token_pepper_fails_without_session_secret():
    """_get_token_pepper() muss fail-fast wenn session_secret fehlt."""
    from relay_server.core.auth import _get_token_pepper

    # session_secret im Test ist gesetzt (siehe conftest/fixture),
    # also testen wir den Pfad ueber eine temporaere Konfiguration.
    original = settings.session_secret
    try:
        settings.session_secret = None
        # _TOKEN_PEPPER global zuruecksetzen
        import relay_server.core.auth as auth_mod

        auth_mod._TOKEN_PEPPER = None
        with pytest.raises(RuntimeError, match="RELAY_SESSION_SECRET"):
            _get_token_pepper()
    finally:
        settings.session_secret = original
        auth_mod._TOKEN_PEPPER = None

