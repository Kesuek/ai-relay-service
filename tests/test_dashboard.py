"""Tests for the dashboard RBAC API endpoints."""

import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ["RELAY_DB_PATH"] = ""
os.environ["RELAY_SESSION_SECRET"] = "test-session-secret-do-not-use-in-production"

from relay_server.config import settings
from relay_server.core.db import init_db
from relay_server.core.session import sign_user_cookie
from relay_server.core.users import create_user
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


def _human_login(username: str, password: str):
    """Log in as a human user and return the response with cookies."""
    return client.post(
        "/relay/v2/dashboard/login",
        data={"mode": "user", "username": username, "password": password},
        follow_redirects=False,
    )


def _admin_node_token():
    """Create an approved admin node and return its runtime token."""
    from relay_server.core.auth import generate_secret, hash_secret
    from relay_server.core.db import get_conn

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
            "node_name": "Admin Node",
            "bootstrap_secret": secret,
            "capabilities": [{"name": "admin", "version": "1.0.0"}],
        },
    )
    assert r.status_code == 200
    return r.json()["token"]


def _mixed_cookies(node_token: str, user: dict):
    """Return a cookie jar containing both relay_token and a signed relay_user."""
    jar = client.cookies.__class__()
    jar.set("relay_token", node_token)
    jar.set("relay_user", sign_user_cookie(user))
    return jar


def test_relay_user_takes_precedence_over_relay_token():
    """A human viewer session must win over a stale admin node token."""
    admin_token = _admin_node_token()
    viewer = create_user("viewer", "password123", group_names=["viewer"])

    cookies = _mixed_cookies(admin_token, viewer)
    r = client.get("/relay/v2/dashboard/api/me", cookies=cookies)
    assert r.status_code == 200
    body = r.json()
    assert body["username"] == "viewer"
    assert body["role"] == "user"
    assert "users:manage" not in body["permissions"]


def test_dashboard_login_clears_stale_relay_token():
    """Logging in as a human user clears any existing relay_token cookie."""
    admin_token = _admin_node_token()
    create_user("adminuser", "password123", group_names=["admin"])

    # Pre-seed the client with a stale admin node token.
    client.cookies.set("relay_token", admin_token)

    r = _human_login("adminuser", "password123")
    assert r.status_code == 303
    # The login response should instruct the browser to delete relay_token.
    assert "relay_token" in r.headers.get("set-cookie", "")
    # And the resulting cookies should not carry the stale node token forward.
    assert "relay_token" not in r.cookies
    assert "relay_user" in r.cookies


def test_human_user_can_manage_users_despite_admin_token_cookie():
    """Mixed cookies with a human admin should still allow user management."""
    admin_token = _admin_node_token()
    adminuser = create_user("adminuser", "password123", group_names=["admin"])

    cookies = _mixed_cookies(admin_token, adminuser)
    r = client.post(
        "/relay/v2/dashboard/api/users",
        data={"username": "newuser", "password": "password123", "groups": "user"},
        cookies=cookies,
    )
    assert r.status_code == 200
    assert r.json()["username"] == "newuser"


def test_api_me_returns_permissions_for_human_user():
    # Create an admin human user.
    create_user("adminuser", "password123", group_names=["admin"])

    r = _human_login("adminuser", "password123")
    assert r.status_code == 303
    cookies = r.cookies

    r = client.get("/relay/v2/dashboard/api/me", cookies=cookies)
    assert r.status_code == 200
    body = r.json()
    assert body["username"] == "adminuser"
    assert "users:manage" in body["permissions"]
    assert "groups:manage" in body["permissions"]


def test_api_me_returns_empty_permissions_for_viewer_user():
    create_user("viewer", "password123", group_names=["viewer"])

    r = _human_login("viewer", "password123")
    cookies = r.cookies

    r = client.get("/relay/v2/dashboard/api/me", cookies=cookies)
    assert r.status_code == 200
    body = r.json()
    assert body["permissions"] == ["dashboard:view", "nodes:view", "tasks:view"]
    assert "users:manage" not in body["permissions"]


def test_users_manage_endpoints_require_permission():
    create_user("viewer", "password123", group_names=["viewer"])
    r = _human_login("viewer", "password123")
    cookies = r.cookies

    r = client.get("/relay/v2/dashboard/api/users", cookies=cookies)
    assert r.status_code == 403

    r = client.post(
        "/relay/v2/dashboard/api/users",
        data={"username": "newuser", "password": "password123", "groups": "user"},
        cookies=cookies,
    )
    assert r.status_code == 403


def test_admin_can_create_user_and_manage_groups():
    create_user("adminuser", "password123", group_names=["admin"])
    r = _human_login("adminuser", "password123")
    cookies = r.cookies

    r = client.post(
        "/relay/v2/dashboard/api/users",
        data={
            "username": "newuser",
            "password": "password123",
            "email": "new@example.com",
            "groups": "user",
        },
        cookies=cookies,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["username"] == "newuser"
    assert body["groups"] == ["user"]

    r = client.get("/relay/v2/dashboard/api/users", cookies=cookies)
    assert r.status_code == 200
    users = r.json()["users"]
    new_user = next(u for u in users if u["username"] == "newuser")

    # Update groups.
    r = client.post(
        f"/relay/v2/dashboard/api/users/{new_user['user_id']}/groups",
        data={"groups": "admin,user"},
        cookies=cookies,
    )
    assert r.status_code == 200

    # Reset password.
    r = client.post(
        f"/relay/v2/dashboard/api/users/{new_user['user_id']}/password",
        data={"password": "newpassword123"},
        cookies=cookies,
    )
    assert r.status_code == 200

    # Toggle active.
    r = client.post(
        f"/relay/v2/dashboard/api/users/{new_user['user_id']}/active",
        data={"active": "false"},
        cookies=cookies,
    )
    assert r.status_code == 200

    # Delete user.
    r = client.delete(
        f"/relay/v2/dashboard/api/users/{new_user['user_id']}",
        cookies=cookies,
    )
    assert r.status_code == 200


def test_groups_manage_endpoints_require_permission():
    create_user("viewer", "password123", group_names=["viewer"])
    r = _human_login("viewer", "password123")
    cookies = r.cookies

    r = client.get("/relay/v2/dashboard/api/groups", cookies=cookies)
    assert r.status_code == 403

    r = client.get("/relay/v2/dashboard/api/permissions", cookies=cookies)
    assert r.status_code == 403

    r = client.post(
        "/relay/v2/dashboard/api/groups/grp_user/permissions",
        data={"permissions": "dashboard:view"},
        cookies=cookies,
    )
    assert r.status_code == 403


def test_admin_can_update_group_permissions():
    create_user("adminuser", "password123", group_names=["admin"])
    r = _human_login("adminuser", "password123")
    cookies = r.cookies

    r = client.get("/relay/v2/dashboard/api/groups", cookies=cookies)
    assert r.status_code == 200
    groups = {g["group_name"]: g for g in r.json()["groups"]}
    user_group_id = groups["user"]["group_id"]

    r = client.get("/relay/v2/dashboard/api/permissions", cookies=cookies)
    assert r.status_code == 200
    permission_names = [p["permission_name"] for p in r.json()["permissions"]]
    assert "users:manage" in permission_names

    r = client.post(
        f"/relay/v2/dashboard/api/groups/{user_group_id}/permissions",
        data={"permissions": "dashboard:view,users:manage"},
        cookies=cookies,
    )
    assert r.status_code == 200

    r = client.get("/relay/v2/dashboard/api/groups", cookies=cookies)
    assert r.status_code == 200
    updated = next(g for g in r.json()["groups"] if g["group_id"] == user_group_id)
    assert "users:manage" in updated["permissions"]


def test_plain_json_user_cookie_is_rejected():
    """A plain JSON relay_user cookie must be rejected as a forgery."""
    cookies = {"relay_user": '{"user_id": "__master__", "username": "master"}'}
    r = client.get("/relay/v2/dashboard/api/me", cookies=cookies)
    assert r.status_code == 401


def test_tampered_signed_user_cookie_is_rejected():
    """A valid signed cookie that has been tampered with must be rejected."""
    create_user("adminuser", "password123", group_names=["admin"])
    r = _human_login("adminuser", "password123")
    signed_cookie = r.cookies.get("relay_user")
    assert signed_cookie

    tampered = signed_cookie[:-5] + ("XXXXX" if signed_cookie[-5:] != "XXXXX" else "YYYYY")
    # Set the tampered value directly on the client cookie jar so it is sent verbatim.
    client.cookies.clear()
    client.cookies.set("relay_user", tampered)
    r = client.get("/relay/v2/dashboard/api/me")
    assert r.status_code == 401


def test_user_cookie_signed_with_wrong_secret_is_rejected():
    """A cookie signed with a different server secret must be rejected."""
    original_secret = settings.session_secret
    try:
        settings.session_secret = "attacker-secret"
        forged = sign_user_cookie({"user_id": "__master__", "username": "master"})
    finally:
        settings.session_secret = original_secret

    r = client.get("/relay/v2/dashboard/api/me", cookies={"relay_user": forged})
    assert r.status_code == 401


def test_master_seed_login_cookie_is_signed():
    """Logging in via master seed should issue a signed relay_user cookie."""
    from relay_server.core.auth import init_master_seed

    seed = init_master_seed()
    assert seed
    r = client.post(
        "/relay/v2/dashboard/login",
        data={"mode": "seed", "seed": seed},
        follow_redirects=False,
    )
    assert r.status_code == 303
    signed_cookie = r.cookies.get("relay_user")
    assert signed_cookie
    assert signed_cookie != '{"user_id":"__master__","username":"master"}'

    r = client.get("/relay/v2/dashboard/api/me", cookies=r.cookies)
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == "__master__"
    assert body["is_master"] is True
