"""Tests for the dashboard RBAC API endpoints."""

import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ["RELAY_DB_PATH"] = ""
os.environ["RELAY_SESSION_SECRET"] = "test-session-secret-do-not-use-in-production"

from relay_server.config import settings
from relay_server.core.auth import init_master_seed
from relay_server.core.db import init_db
from relay_server.core.session import generate_csrf_token, sign_user_cookie
from relay_server.core.users import create_user
from relay_server.main import app


@pytest.fixture(autouse=True)
def fresh_db():
    """Use a temporary database for each test."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        settings.db_path = db_path
        settings.session_secret = "test-session-secret-do-not-use-in-production"
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


def _csrf_headers(response=None):
    """Return headers with a CSRF token that matches the request cookies."""
    csrf_cookie = response.cookies.get("relay_csrf") if response else None
    if not csrf_cookie:
        # httpx Cookie jar may contain duplicates; pick the first relay_csrf value.
        for cookie in client.cookies.jar:
            if cookie.name == "relay_csrf":
                csrf_cookie = cookie.value
                break
    if not csrf_cookie:
        csrf_cookie = generate_csrf_token()
    return {"X-CSRF-Token": csrf_cookie}


def _login_cookie_flags():
    r = _human_login("viewer", "strong-passphrase-42")
    flags = {}
    cookies = r.headers.get_list("set-cookie")
    for c in cookies:
        if c.startswith("relay_user"):
            flags["httponly"] = "HttpOnly" in c
            flags["samesite"] = "SameSite=Lax" in c or "SameSite=lax" in c
            flags["max_age"] = "Max-Age=604800" in c
            flags["secure"] = "Secure" in c
    return flags


def test_dashboard_session_cookie_has_security_flags():
    create_user(
        "viewer", "strong-passphrase-42", group_names=["viewer"], force_password_change=False,
    )
    flags = _login_cookie_flags()
    assert flags.get("httponly") is True
    assert flags.get("samesite") is True
    assert flags.get("max_age") is True
    assert flags.get("secure") is False  # disabled in test settings


def test_security_headers_present():
    r = client.get("/health")
    assert r.status_code == 200
    assert "Content-Security-Policy" in r.headers
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]


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


def test_dashboard_rejects_node_token_cookie():
    """A node runtime token provided as relay_token cookie must not authenticate the dashboard."""
    admin_token = _admin_node_token()

    r = client.get(
        "/relay/v2/dashboard/api/me",
        cookies={"relay_token": admin_token},
    )
    assert r.status_code == 401


def test_relay_user_takes_precedence_over_relay_token():
    """A human viewer session must win over a stale admin node token."""
    admin_token = _admin_node_token()
    viewer = create_user(
        "viewer", "strong-passphrase-42",
        group_names=["viewer"], force_password_change=False,
    )

    cookies = _mixed_cookies(admin_token, viewer)
    r = client.get("/relay/v2/dashboard/api/me", cookies=cookies)
    assert r.status_code == 200
    body = r.json()
    assert body["username"] == "viewer"
    assert body["role"] == "user"
    assert "users:manage" not in body["permissions"]


def test_dashboard_login_clears_stale_relay_token():
    """Logging in as a human user must not set or keep a relay_token cookie."""
    admin_token = _admin_node_token()
    create_user(
        "adminuser", "strong-passphrase-42", group_names=["admin"], force_password_change=False,
    )

    # Pre-seed the client with a stale admin node token.
    client.cookies.set("relay_token", admin_token)

    r = _human_login("adminuser", "strong-passphrase-42")
    assert r.status_code == 303
    # The dashboard no longer uses relay_token; only relay_user should appear.
    set_cookie_header = r.headers.get("set-cookie", "")
    assert "relay_user" in set_cookie_header
    assert "relay_token" not in set_cookie_header
    assert "relay_token" not in r.cookies
    assert "relay_user" in r.cookies


def test_human_user_can_manage_users_despite_admin_token_cookie():
    """Mixed cookies with a human admin should still allow user management."""
    admin_token = _admin_node_token()
    adminuser = create_user(
        "adminuser", "strong-passphrase-42",
        group_names=["admin"], force_password_change=False,
    )

    cookies = _mixed_cookies(admin_token, adminuser)
    csrf_cookie = generate_csrf_token()
    cookies.set("relay_csrf", csrf_cookie)
    r = client.post(
        "/relay/v2/dashboard/api/users",
        data={"username": "newuser", "password": "strong-passphrase-42", "groups": "user"},
        cookies=cookies,
        headers={"X-CSRF-Token": csrf_cookie},
    )
    assert r.status_code == 200
    assert r.json()["username"] == "newuser"


def test_api_me_returns_permissions_for_human_user():
    # Create an admin human user.
    create_user(
        "adminuser", "strong-passphrase-42", group_names=["admin"], force_password_change=False,
    )

    r = _human_login("adminuser", "strong-passphrase-42")
    assert r.status_code == 303
    cookies = r.cookies

    r = client.get("/relay/v2/dashboard/api/me", cookies=cookies)
    assert r.status_code == 200
    body = r.json()
    assert body["username"] == "adminuser"
    assert "users:manage" in body["permissions"]
    assert "groups:manage" in body["permissions"]


def test_api_me_returns_empty_permissions_for_viewer_user():
    create_user(
        "viewer", "strong-passphrase-42", group_names=["viewer"], force_password_change=False,
    )

    r = _human_login("viewer", "strong-passphrase-42")
    cookies = r.cookies

    r = client.get("/relay/v2/dashboard/api/me", cookies=cookies)
    assert r.status_code == 200
    body = r.json()
    assert body["permissions"] == ["dashboard:view", "nodes:view", "tasks:view"]
    assert "users:manage" not in body["permissions"]


def test_users_manage_endpoints_require_permission():
    create_user(
        "viewer", "strong-passphrase-42", group_names=["viewer"], force_password_change=False,
    )
    r = _human_login("viewer", "strong-passphrase-42")
    cookies = r.cookies

    r = client.get("/relay/v2/dashboard/api/users", cookies=cookies)
    assert r.status_code == 403

    r = client.post(
        "/relay/v2/dashboard/api/users",
        data={"username": "newuser", "password": "strong-passphrase-42", "groups": "user"},
        cookies=cookies,
        headers=_csrf_headers(r),
    )
    assert r.status_code == 403


def test_admin_can_create_user_and_manage_groups():
    create_user(
        "adminuser", "strong-passphrase-42", group_names=["admin"], force_password_change=False,
    )
    r = _human_login("adminuser", "strong-passphrase-42")
    cookies = r.cookies
    _csrf_cookie = cookies.get("relay_csrf")

    r = client.post(
        "/relay/v2/dashboard/api/users",
        data={
            "username": "newuser",
            "password": "strong-passphrase-42",
            "email": "new@example.com",
            "groups": "user",
        },
        cookies=cookies,
        headers=_csrf_headers(r),
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
        headers=_csrf_headers(r),
    )
    assert r.status_code == 200

    # Reset password.
    r = client.post(
        f"/relay/v2/dashboard/api/users/{new_user['user_id']}/password",
        data={"password": "new-strong-passphrase-99"},
        cookies=cookies,
        headers=_csrf_headers(r),
    )
    assert r.status_code == 200

    # Toggle active.
    r = client.post(
        f"/relay/v2/dashboard/api/users/{new_user['user_id']}/active",
        data={"active": "false"},
        cookies=cookies,
        headers=_csrf_headers(r),
    )
    assert r.status_code == 200

    # Delete user.
    r = client.delete(
        f"/relay/v2/dashboard/api/users/{new_user['user_id']}",
        cookies=cookies,
        headers=_csrf_headers(r),
    )
    assert r.status_code == 200


def test_groups_manage_endpoints_require_permission():
    create_user(
        "viewer", "strong-passphrase-42", group_names=["viewer"], force_password_change=False,
    )
    r = _human_login("viewer", "strong-passphrase-42")
    cookies = r.cookies

    r = client.get("/relay/v2/dashboard/api/groups", cookies=cookies)
    assert r.status_code == 403

    r = client.get("/relay/v2/dashboard/api/permissions", cookies=cookies)
    assert r.status_code == 403

    r = client.post(
        "/relay/v2/dashboard/api/groups/grp_user/permissions",
        data={"permissions": "dashboard:view"},
        cookies=cookies,
        headers=_csrf_headers(r),
    )
    assert r.status_code == 403


def test_admin_can_update_group_permissions():
    create_user(
        "adminuser", "strong-passphrase-42", group_names=["admin"], force_password_change=False,
    )
    r = _human_login("adminuser", "strong-passphrase-42")
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
        headers=_csrf_headers(r),
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
    create_user(
        "adminuser", "strong-passphrase-42", group_names=["admin"], force_password_change=False,
    )
    r = _human_login("adminuser", "strong-passphrase-42")
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


def test_master_seed_login_cookie_has_short_ttl():
    """Master-seed session cookie must use the 1h TTL, not the 7d default (T-025)."""
    from relay_server.core.auth import init_master_seed
    from relay_server.core.session import (
        MASTER_SEED_SESSION_MAX_AGE_SECONDS,
        SESSION_MAX_AGE_SECONDS,
        unsign_user_cookie,
    )

    seed = init_master_seed()
    assert seed
    r = client.post(
        "/relay/v2/dashboard/login",
        data={"mode": "seed", "seed": seed},
        follow_redirects=False,
    )
    assert r.status_code == 303

    # The Set-Cookie header must carry the shortened max-age.
    set_cookie = r.headers.get("set-cookie", "")
    # relay_user cookie should specify Max-Age=3600 (1h).
    assert "relay_user=" in set_cookie
    assert f"Max-Age={MASTER_SEED_SESSION_MAX_AGE_SECONDS}" in set_cookie
    assert f"Max-Age={SESSION_MAX_AGE_SECONDS}" not in set_cookie

    # The signed payload must embed the shorter max_age so unsign
    # enforces it independent of the global default.
    signed_cookie = r.cookies.get("relay_user")
    assert signed_cookie
    payload = unsign_user_cookie(signed_cookie)
    assert payload is not None
    assert payload.get("_max_age") == MASTER_SEED_SESSION_MAX_AGE_SECONDS


def test_human_login_cookie_uses_default_ttl():
    """Regular human user sessions keep the 7d TTL (T-025 regression guard)."""
    from relay_server.core.session import SESSION_MAX_AGE_SECONDS

    create_user(
        username="ttluser",
        password="strong-passphrase-42",
        group_names=["viewer"],
        email=None,
        created_by="test",
    )
    r = _human_login("ttluser", "strong-passphrase-42")
    assert r.status_code == 303
    set_cookie = r.headers.get("set-cookie", "")
    assert "relay_user=" in set_cookie
    assert f"Max-Age={SESSION_MAX_AGE_SECONDS}" in set_cookie


def test_master_seed_login_disabled_after_admin_exists():
    """Master-seed login must be blocked once a human admin exists."""
    from relay_server.core.auth import init_master_seed

    seed = init_master_seed()
    assert seed

    # Create a human admin first.
    create_user(
        "recovery-admin", "another-strong-passphrase-88",
        group_names=["admin"], force_password_change=False,
    )

    r = client.post(
        "/relay/v2/dashboard/login",
        data={"mode": "seed", "seed": seed},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "Seed%20login%20disabled" in r.headers["location"]

    # Human admin login still works.
    r = _human_login("recovery-admin", "another-strong-passphrase-88")
    assert r.status_code == 303
    assert r.cookies.get("relay_user")


def test_new_user_forced_to_change_password():
    """A user created with force_password_change=True is redirected
    to the password change page on login."""
    from relay_server.core.users import create_user

    init_db()
    temp_password = "temp-passphrase-99"
    create_user(
        username="newadmin",
        password=temp_password,
        group_names=["admin"],
        force_password_change=True,
    )

    r = client.post(
        "/relay/v2/dashboard/login",
        data={"mode": "user", "username": "newadmin", "password": temp_password},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "/relay/v2/dashboard/change-password" in r.headers["location"]

    # Normal dashboard access is blocked until password is changed.
    r = client.get("/relay/v2/dashboard/api/me", cookies=r.cookies)
    assert r.status_code == 403
    assert "Password change required" in r.text


def test_user_can_change_own_password():
    """A user with force_password_change can change their password and then access the dashboard."""
    from relay_server.core.users import create_user

    init_db()
    temp_password = "temp-passphrase-99"
    new_password = "new-strong-passphrase-99"
    create_user(
        username="newadmin",
        password=temp_password,
        group_names=["admin"],
        force_password_change=True,
    )

    r = client.post(
        "/relay/v2/dashboard/login",
        data={"mode": "user", "username": "newadmin", "password": temp_password},
        follow_redirects=False,
    )
    cookies = r.cookies

    r = client.post(
        "/relay/v2/dashboard/api/me/password",
        data={"current_password": temp_password, "new_password": new_password},
        cookies=cookies,
        headers=_csrf_headers(r),
    )
    assert r.status_code == 200

    # Second login with new password works normally.
    r = client.post(
        "/relay/v2/dashboard/login",
        data={"mode": "user", "username": "newadmin", "password": new_password},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "/relay/v2/dashboard/" in r.headers["location"]
    assert "/change-password" not in r.headers["location"]

    r = client.get("/relay/v2/dashboard/api/me", cookies=r.cookies)
    assert r.status_code == 200


def test_master_seed_login_redirects_to_bootstrap():
    """After master seed login, the user is redirected to the bootstrap page."""
    init_db()
    seed = init_master_seed()
    r = client.post(
        "/relay/v2/dashboard/login",
        data={"mode": "seed", "seed": seed},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "/relay/v2/dashboard/bootstrap" in r.headers["location"]


def test_bootstrap_creates_first_admin_with_temporary_password():
    """The bootstrap endpoint creates an admin with a temporary password via master seed session."""
    init_db()
    seed = init_master_seed()
    r = client.post(
        "/relay/v2/dashboard/login",
        data={"mode": "seed", "seed": seed},
        follow_redirects=False,
    )
    client.cookies.set("relay_user", r.cookies["relay_user"])
    # Use the CSRF cookie from the login response.
    csrf_cookie = r.cookies.get("relay_csrf", generate_csrf_token())
    client.cookies.set("relay_csrf", csrf_cookie)

    r = client.post(
        "/relay/v2/dashboard/api/bootstrap",
        data={"username": "bootadmin", "email": "boot@example.com"},
        headers={"X-CSRF-Token": csrf_cookie},
    )
    if r.status_code != 200:
        print(r.status_code, r.text)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "temporary_password" in data
    assert len(data["temporary_password"]) >= 16

    # After bootstrap, master seed login should be disabled.
    r = client.post(
        "/relay/v2/dashboard/login",
        data={"mode": "seed", "seed": seed},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "disabled" in r.headers["location"]


def test_public_docs_index():
    """The docs index lists public documents and their URLs."""
    r = client.get("/relay/v2/docs")
    assert r.status_code == 200
    data = r.json()
    assert "docs" in data
    names = {d["name"] for d in data["docs"]}
    assert "readme" in names
    assert "node-setup" in names
    assert "concepts" in names
    for doc in data["docs"]:
        assert doc["url"].startswith("/relay/v2/docs/")
        assert "available" in doc


def test_public_docs_render_markdown_as_html():
    """A known document is rendered as HTML and contains expected content."""
    r = client.get("/relay/v2/docs/node-setup")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "<html" in r.text
    assert "AI Relay" in r.text


def test_public_docs_unknown_returns_404():
    """Unknown document names return 404."""
    r = client.get("/relay/v2/docs/unknown-doc")
    assert r.status_code == 404


def test_dashboard_agent_readme_redirects_to_public_docs():
    """The old dashboard agent-readme URL redirects to the new public docs path."""
    r = client.get("/relay/v2/dashboard/agent-readme", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/relay/v2/docs/node-setup"
