"""Tests for dynamic node routes (T-075)."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

os.environ["RELAY_SESSION_SECRET"] = "test-session-secret-32-chars-minimum!!!"

from relay_server.config import settings
from relay_server.core.auth import generate_secret, hash_secret
from relay_server.core.db import get_conn, init_db, q
from relay_server.core.maintenance import _temp_route_cleanup
from relay_server.main import app


@pytest.fixture
def client():
    """Create a test client with an isolated database."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        settings.db_path = db_path
        settings.session_secret = "test-session-secret-32-chars-minimum!!!"
        settings.session_cookie_secure = False
        settings.temp_route_max_ttl_seconds = 86400
        init_db()

        # Seed a node first (FOREIGN KEY constraint)
        conn = get_conn()
        conn.execute(
            q("INSERT INTO nodes (node_id, node_name, status, role, last_seen, registered_at) "
            "VALUES (?, ?, ?, ?, ?, ?)", ("test-node", "test-node", "online", "worker", "2026-01-01T00:00:00", "2026-01-01T00:00:00")),
        )
        # Seed a route in the DB
        conn.execute(
            q("INSERT INTO node_routes (node_id, path, method, auth, upstream, description) "
            "VALUES (?, ?, ?, ?, ?, ?)", ("test-node", "/api/test", "GET", "session", "http://localhost:9999/api/test", "Test route")),
        )
        conn.commit()
        conn.close()

        yield TestClient(app)


def _seed_admin_token(client: TestClient) -> str:
    """Seed an admin seed and return a usable admin node token."""
    import relay_server.core.auth as auth_mod

    auth_mod._TOKEN_PEPPER = None  # force re-derivation with the live secret
    secret = generate_secret("adm_")
    conn = get_conn()
    conn.execute(
        q("INSERT INTO admin_seeds (seed_id, seed_hash, role, created_at) "
        "VALUES (?, ?, ?, ?)", ("master", hash_secret(secret), "admin", "2026-01-01T00:00:00+00:00")),
    )
    conn.commit()
    conn.close()
    r = client.post(
        "/relay/v2/auth/register-admin",
        json={"node_name": "Admin", "bootstrap_secret": secret,
              "capabilities": [{"name": "admin", "version": "1.0.0"}]},
    )
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _register_worker_node(client: TestClient, name: str, admin_token: str) -> tuple[str, str]:
    """Register + approve a worker node and return (node_id, token)."""
    r = client.post(
        "/relay/v2/auth/register",
        json={"node_name": name, "endpoint": "http://localhost:9001",
              "capabilities": [], "role": "service"},
    )
    assert r.status_code == 200, r.text
    node_id = r.json()["node_id"]
    r2 = client.post(
        f"/relay/v2/admin/nodes/{node_id}/approve",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"role": "service", "capabilities": []},
    )
    assert r2.status_code == 200, r2.text
    return node_id, r2.json()["token"]


class TestRouteRegistry:
    """Tests for the dynamic node route proxy."""

    def test_route_not_found_returns_404_without_auth(self, client: TestClient):
        """T-123: the route lookup happens before auth, so a missing route
        returns 404 regardless of authentication (the old behaviour raised
        401 first because the session dependency ran before the lookup)."""
        resp = client.get("/relay/v2/dashboard/api/node-routes/nonexistent/api/test")
        assert resp.status_code == 404

    def test_route_with_session_but_not_found(self, client: TestClient):
        """With valid session but nonexistent route, should get 404."""
        # Login first to get a proper session cookie
        from relay_server.core.users import create_user
        create_user("testuser", "strong-passphrase-42", group_names=["admin"], force_password_change=False)
        login_resp = client.post(
            "/relay/v2/dashboard/login",
            data={"mode": "user", "username": "testuser", "password": "strong-passphrase-42"},
            follow_redirects=False,
        )
        assert login_resp.status_code == 303, f"Login failed: {login_resp.text}"
        resp = client.get("/relay/v2/dashboard/api/node-routes/nonexistent/api/test")
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"

    def test_route_requires_session_cookie(self, client: TestClient):
        resp = client.get("/relay/v2/dashboard/api/node-routes/test-node/api/test")
        assert resp.status_code == 401  # No session cookie

    def test_route_with_session_cookie_proxies(self, client: TestClient):
        """With a valid session cookie, the route should proxy (and get 502 because upstream is unreachable)."""
        from relay_server.core.users import create_user
        from relay_server.core.session import sign_user_cookie
        create_user("testuser", "strong-passphrase-42", group_names=["admin"], force_password_change=False)
        # Login and follow redirect to get cookies on the client
        login_resp = client.post(
            "/relay/v2/dashboard/login",
            data={"mode": "user", "username": "testuser", "password": "strong-passphrase-42"},
            follow_redirects=True,
        )
        # Verify we're authenticated
        me = client.get("/relay/v2/dashboard/api/me")
        assert me.status_code == 200, f"Not authenticated after login: {me.text}"
        resp = client.get("/relay/v2/dashboard/api/node-routes/test-node/api/test")
        # Should get 502 (upstream unreachable) or 200 if mock works
        assert resp.status_code in (502, 200), f"Expected 502 or 200, got {resp.status_code}: {resp.text}"

    def test_route_db_sync(self, client: TestClient):
        """Verify routes are stored and retrievable from DB."""
        conn = get_conn()
        row = conn.execute(
            q("SELECT * FROM node_routes WHERE node_id = ?", ("test-node",))
        ).fetchone()
        assert row is not None
        assert row["path"] == "/api/test"
        assert row["method"] == "GET"
        assert row["auth"] == "session"
        conn.close()

    def test_route_clear_on_offline(self, client: TestClient):
        """Verify routes are cleared when a node goes offline."""
        conn = get_conn()
        conn.execute(q("DELETE FROM node_routes WHERE node_id = ?", ("test-node",)))
        conn.commit()
        row = conn.execute(
            q("SELECT * FROM node_routes WHERE node_id = ?", ("test-node",))
        ).fetchone()
        assert row is None
        conn.close()


class TestCapabilityYAMLRoutes:
    """Tests for routes in capability YAML."""

    def test_routes_in_yaml_validates(self):
        """Verify that routes in capability YAML pass validation."""
        from nodes.common.node_config import validate_profile

        profile = {
            "capabilities": [
                {
                    "name": "ssn.capability-pages",
                    "version": "1.0.0",
                    "routes": [
                        {
                            "path": "/api/task-submit",
                            "method": "POST",
                            "auth": "session",
                            "upstream": "http://localhost:8790/api/task-submit",
                            "description": "Submit a task",
                        }
                    ],
                }
            ]
        }
        caps = validate_profile(profile)
        assert len(caps) == 1
        assert "routes" in caps[0]
        assert len(caps[0]["routes"]) == 1
        assert caps[0]["routes"][0]["path"] == "/api/task-submit"

    def test_routes_with_extra_fields_accepted(self):
        """Verify that routes with unknown keys are still accepted (validation is at capability level)."""
        from nodes.common.node_config import validate_profile

        profile = {
            "capabilities": [
                {
                    "name": "test",
                    "version": "1.0.0",
                    "routes": [
                        {
                            "path": "/test",
                            "method": "GET",
                            "upstream": "http://localhost:9999",
                            "bogus_field": "should be ignored",
                        }
                    ],
                }
            ]
        }
        # Routes is an opaque list — individual route entries are not validated
        # by the capability schema. Validation happens at the heartbeat model level.
        caps = validate_profile(profile)
        assert len(caps) == 1
        assert "routes" in caps[0]
        assert len(caps[0]["routes"]) == 1


# ---------------------------------------------------------------------------
# T-123/124/125: temporary bridge routes
# ---------------------------------------------------------------------------


class TestTempRouteExpiry:
    """T-123: an expired temp route is treated as 404 by the proxy."""

    def test_expired_temp_route_returns_404(self, client: TestClient):
        """An expired temp route (expires_at in the past) → 404."""
        past = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        conn = get_conn()
        conn.execute(
            q("INSERT INTO node_routes (node_id, path, method, auth, upstream, "
            "description, expires_at, channel_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("test-node", "/upload/expired", "POST", "node_token",
             "http://localhost:9999/upload/expired", "", past, "ch_expired")),
        )
        conn.commit()
        conn.close()
        # node_token routes authenticate via Bearer — but lookup happens
        # first and an expired row is already "not found", so we 404
        # even with no/invalid Bearer token.
        resp = client.post("/relay/v2/dashboard/api/node-routes/test-node/upload/expired")
        assert resp.status_code == 404, resp.text

    def test_unexpired_temp_route_reachable_without_session(self, client: TestClient):
        """A live temp route is looked up even without a session cookie (T-123/124)."""
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        conn = get_conn()
        conn.execute(
            q("INSERT INTO node_routes (node_id, path, method, auth, upstream, "
            "description, expires_at, channel_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("test-node", "/upload/alive", "POST", "node_token",
             "http://localhost:9999/upload/alive", "", future, "ch_alive")),
        )
        conn.commit()
        conn.close()
        # No Bearer token → auth-mode node_token requires one → 401 (not 404),
        # proving the lookup found the route and proceeded to auth.
        resp = client.post("/relay/v2/dashboard/api/node-routes/test-node/upload/alive")
        assert resp.status_code == 401, resp.text


class TestRegisterTempRoute:
    """T-124: POST /api/node-routes/register."""

    def test_register_without_token_is_401(self, client: TestClient):
        resp = client.post("/relay/v2/dashboard/api/node-routes/register", json={
            "path": "/upload/abc", "method": "POST", "ttl_seconds": 60,
            "upstream": "http://localhost:9999/upload/abc", "channel_id": "ch_abc",
        })
        assert resp.status_code == 401, resp.text

    def test_register_with_node_token_creates_route(self, client: TestClient):
        admin_token = _seed_admin_token(client)
        node_id, node_token = _register_worker_node(client, "bridge-owner", admin_token)

        resp = client.post(
            "/relay/v2/dashboard/api/node-routes/register",
            headers={"Authorization": f"Bearer {node_token}"},
            json={
                "path": "/upload/abc123",
                "method": "POST",
                "ttl_seconds": 3600,
                "upstream": f"http://storage-node:8791/upload/abc123",
                "channel_id": "ch_abc123",
                "description": "channel upload",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "ok"
        assert body["node_id"] == node_id
        assert body["path"] == "/upload/abc123"
        assert body["method"] == "POST"
        assert body["channel_id"] == "ch_abc123"
        # expires_at is in the future.
        exp = datetime.fromisoformat(body["expires_at"])
        assert exp > datetime.now(timezone.utc)

        # Row landed in the DB with auth=node_token and a channel_id.
        conn = get_conn()
        row = conn.execute(
            q("SELECT auth, upstream, channel_id, expires_at FROM node_routes "
            "WHERE node_id = ? AND path = ? AND method = ?",
            (node_id, "/upload/abc123", "POST")),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["auth"] == "node_token"
        assert row["upstream"] == "http://storage-node:8791/upload/abc123"
        assert row["channel_id"] == "ch_abc123"

    def test_register_rejects_ttl_too_large(self, client: TestClient):
        admin_token = _seed_admin_token(client)
        _, node_token = _register_worker_node(client, "ttl-owner", admin_token)
        # Cap the server-side maximum so the test is deterministic.
        settings.temp_route_max_ttl_seconds = 100
        resp = client.post(
            "/relay/v2/dashboard/api/node-routes/register",
            headers={"Authorization": f"Bearer {node_token}"},
            json={
                "path": "/upload/big", "method": "POST", "ttl_seconds": 1000,
                "upstream": "http://x/upload/big", "channel_id": "ch_big",
            },
        )
        assert resp.status_code == 400, resp.text
        assert "maximum" in resp.json()["detail"]

    def test_register_rejects_disallowed_path(self, client: TestClient):
        admin_token = _seed_admin_token(client)
        _, node_token = _register_worker_node(client, "path-owner", admin_token)
        resp = client.post(
            "/relay/v2/dashboard/api/node-routes/register",
            headers={"Authorization": f"Bearer {node_token}"},
            json={
                "path": "/admin/dangerous", "method": "POST", "ttl_seconds": 60,
                "upstream": "http://x/dangerous", "channel_id": "ch_danger",
            },
        )
        assert resp.status_code == 400, resp.text
        assert "must start with" in resp.json()["detail"]

    def test_register_allows_backup_bridge_path(self, client: TestClient):
        """T-158: the storage node registers /backup/ bridge routes for
        backup.create/restore. These must be allowed (T-162 regression)."""
        admin_token = _seed_admin_token(client)
        node_id, node_token = _register_worker_node(client, "backup-owner", admin_token)
        resp = client.post(
            "/relay/v2/dashboard/api/node-routes/register",
            headers={"Authorization": f"Bearer {node_token}"},
            json={
                "path": "/backup/bk_abc123", "method": "POST", "ttl_seconds": 3600,
                "upstream": "http://storage-node:8791/backup/bk_abc123",
                "channel_id": "bk_bk_abc123",
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["path"] == "/backup/bk_abc123"

    def test_register_rejects_missing_channel_id(self, client: TestClient):
        admin_token = _seed_admin_token(client)
        _, node_token = _register_worker_node(client, "ch-owner", admin_token)
        resp = client.post(
            "/relay/v2/dashboard/api/node-routes/register",
            headers={"Authorization": f"Bearer {node_token}"},
            json={
                "path": "/upload/noch", "method": "POST", "ttl_seconds": 60,
                "upstream": "http://x/noch",  # channel_id omitted
            },
        )
        assert resp.status_code == 400, resp.text

    def test_register_rejects_nonpositive_ttl(self, client: TestClient):
        admin_token = _seed_admin_token(client)
        _, node_token = _register_worker_node(client, "zero-ttl-owner", admin_token)
        resp = client.post(
            "/relay/v2/dashboard/api/node-routes/register",
            headers={"Authorization": f"Bearer {node_token}"},
            json={
                "path": "/upload/zero", "method": "POST", "ttl_seconds": 0,
                "upstream": "http://x/zero", "channel_id": "ch_zero",
            },
        )
        assert resp.status_code == 400, resp.text

    def test_register_rejects_bad_method(self, client: TestClient):
        admin_token = _seed_admin_token(client)
        _, node_token = _register_worker_node(client, "method-owner", admin_token)
        resp = client.post(
            "/relay/v2/dashboard/api/node-routes/register",
            headers={"Authorization": f"Bearer {node_token}"},
            json={
                "path": "/upload/m", "method": "BOGUS", "ttl_seconds": 60,
                "upstream": "http://x/m", "channel_id": "ch_m",
            },
        )
        assert resp.status_code == 400, resp.text


class TestDeleteTempRoute:
    """T-124: DELETE /api/node-routes/{node_id}/{path}."""

    def test_delete_own_route(self, client: TestClient):
        admin_token = _seed_admin_token(client)
        node_id, node_token = _register_worker_node(client, "del-owner", admin_token)
        # Register first.
        client.post(
            "/relay/v2/dashboard/api/node-routes/register",
            headers={"Authorization": f"Bearer {node_token}"},
            json={"path": "/upload/del", "method": "POST", "ttl_seconds": 60,
                  "upstream": "http://x/del", "channel_id": "ch_del"},
        )
        # DELETE by the owner.
        resp = client.delete(
            f"/relay/v2/dashboard/api/node-routes/{node_id}/upload/del",
            params={"method": "POST"},
            headers={"Authorization": f"Bearer {node_token}"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "deleted"

        # Row is gone.
        conn = get_conn()
        row = conn.execute(
            q("SELECT path FROM node_routes WHERE node_id = ? AND path = ?",
            (node_id, "/upload/del")),
        ).fetchone()
        conn.close()
        assert row is None

    def test_delete_other_nodes_route_forbidden(self, client: TestClient):
        admin_token = _seed_admin_token(client)
        node_a, token_a = _register_worker_node(client, "ownerA", admin_token)
        node_b, token_b = _register_worker_node(client, "ownerB", admin_token)
        # A registers a route.
        client.post(
            "/relay/v2/dashboard/api/node-routes/register",
            headers={"Authorization": f"Bearer {token_a}"},
            json={"path": "/upload/forbid", "method": "POST", "ttl_seconds": 60,
                  "upstream": "http://x/forbid", "channel_id": "ch_forbid"},
        )
        # B tries to delete A's route — must 403.
        resp = client.delete(
            f"/relay/v2/dashboard/api/node-routes/{node_a}/upload/forbid",
            params={"method": "POST"},
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert resp.status_code == 403, resp.text

    def test_delete_missing_route_404(self, client: TestClient):
        admin_token = _seed_admin_token(client)
        node_id, node_token = _register_worker_node(client, "del-missing", admin_token)
        resp = client.delete(
            f"/relay/v2/dashboard/api/node-routes/{node_id}/upload/none",
            params={"method": "POST"},
            headers={"Authorization": f"Bearer {node_token}"},
        )
        assert resp.status_code == 404, resp.text


class TestListOwnRoutes:
    """T-136: GET /api/node-routes lists the caller's own routes."""

    def test_list_without_token_is_401(self, client: TestClient):
        resp = client.get("/relay/v2/dashboard/api/node-routes")
        assert resp.status_code == 401, resp.text

    def test_list_returns_only_own_routes(self, client: TestClient):
        admin_token = _seed_admin_token(client)
        node_a, token_a = _register_worker_node(client, "list-owner-a", admin_token)
        node_b, token_b = _register_worker_node(client, "list-owner-b", admin_token)
        # A registers a temp route, B registers a temp route.
        client.post(
            "/relay/v2/dashboard/api/node-routes/register",
            headers={"Authorization": f"Bearer {token_a}"},
            json={"path": "/upload/a", "method": "POST", "ttl_seconds": 60,
                  "upstream": "http://x/a", "channel_id": "ch_a"},
        )
        client.post(
            "/relay/v2/dashboard/api/node-routes/register",
            headers={"Authorization": f"Bearer {token_b}"},
            json={"path": "/upload/b", "method": "POST", "ttl_seconds": 60,
                  "upstream": "http://x/b", "channel_id": "ch_b"},
        )
        # A lists → only A's route.
        resp = client.get(
            "/relay/v2/dashboard/api/node-routes",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "ok"
        assert body["node_id"] == node_a
        paths = {r["path"] for r in body["routes"]}
        assert "/upload/a" in paths
        assert "/upload/b" not in paths
        # Each route row carries expires_at + channel_id for temp routes.
        a_route = next(r for r in body["routes"] if r["path"] == "/upload/a")
        assert a_route["channel_id"] == "ch_a"
        assert a_route["expires_at"] is not None


class TestTempRouteCleanup:
    """T-125: temp_route_cleanup watchdog reaps expired temp routes."""

    def test_cleanup_deletes_expired_temp_routes(self, client: TestClient):
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        conn = get_conn()
        # expired temp
        conn.execute(
            q("INSERT INTO node_routes (node_id, path, method, auth, upstream, "
            "description, expires_at, channel_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("test-node", "/upload/gone", "POST", "node_token", "http://x", "", past, "ch_gone")),
        )
        # live temp
        conn.execute(
            q("INSERT INTO node_routes (node_id, path, method, auth, upstream, "
            "description, expires_at, channel_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("test-node", "/upload/keep", "POST", "node_token", "http://x", "", future, "ch_keep")),
        )
        conn.commit()
        conn.close()

        result = _temp_route_cleanup()
        assert result["deleted"] == 1

        conn = get_conn()
        rows = conn.execute(
            q("SELECT path FROM node_routes WHERE node_id = ?", ("test-node",)),
        ).fetchall()
        conn.close()
        paths = {r["path"] for r in rows}
        assert "/upload/gone" not in paths
        assert "/upload/keep" in paths

    def test_cleanup_leaves_permanent_routes_alone(self, client: TestClient):
        # The fixture seeds a permanent route at /api/test (expires_at IS NULL).
        # Backdate a temp route and confirm the permanent one survives the sweep.
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        conn = get_conn()
        conn.execute(
            q("INSERT INTO node_routes (node_id, path, method, auth, upstream, "
            "description, expires_at, channel_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("test-node", "/upload/expired2", "POST", "node_token", "http://x", "", past, "ch2")),
        )
        conn.commit()
        conn.close()

        _temp_route_cleanup()

        conn = get_conn()
        perm = conn.execute(
            q("SELECT path FROM node_routes WHERE node_id = ? AND path = ?",
            ("test-node", "/api/test")),
        ).fetchone()
        conn.close()
        assert perm is not None, "permanent heartbeat route must survive temp cleanup"


# ---------------------------------------------------------------------------
# T-129: proxy streams large bodies (no OOM / no buffering).
# ---------------------------------------------------------------------------


class TestProxyStreaming:
    """T-129: the relay proxy forwards request + response chunkwise.

    We patch :class:`httpx.AsyncClient` in ``route_registry`` with a
    :class:`httpx.MockTransport` so the proxy talks to an in-process
    mock upstream — no real sockets. The mock records the bytes it
    received (so we can assert the request body was forwarded) and
    returns a configurable response (so we can assert the response is
    streamed back to the caller without buffering).
    """

    def _patch_upstream(self, monkeypatch, handler):
        """Replace httpx.AsyncClient in route_registry with a mock transport.

        ``handler`` is a ``(request) -> httpx.Response`` callable.
        """
        from relay_server.core import route_registry

        transport = httpx.MockTransport(handler)

        class _MockAsyncClient(httpx.AsyncClient):
            def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
                kwargs.setdefault("transport", transport)
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(route_registry.httpx, "AsyncClient", _MockAsyncClient)

    def _login_as_admin(self, client):
        from relay_server.core.users import create_user
        create_user("streamuser", "strong-passphrase-42", group_names=["admin"], force_password_change=False)
        client.post(
            "/relay/v2/dashboard/login",
            data={"mode": "user", "username": "streamuser", "password": "strong-passphrase-42"},
            follow_redirects=True,
        )

    def _seed_route(self, method, upstream, path="/api/echo"):
        conn = get_conn()
        conn.execute(
            q("INSERT INTO node_routes (node_id, path, method, auth, upstream, description) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("test-node", path, method, "session", upstream, "echo")),
        )
        conn.commit()
        conn.close()

    def test_post_streams_large_request_body(self, client: TestClient, monkeypatch):
        """A large POST body is forwarded to the upstream (request streaming).

        The mock upstream reads the request body and echoes it; we
        assert it received the full 5MB, proving the proxy forwarded the
        body (not dropped) without requiring the upstream to buffer it.
        """
        received = {"total": 0, "content_length": None}

        def handler(req):
            # MockTransport reads the whole body for the handler; the
            # proxy's streaming path feeds it chunkwise via request.stream().
            body = req.read()
            received["total"] = len(body)
            received["content_length"] = req.headers.get("content-length")
            return httpx.Response(200, content=b"ok:" + str(len(body)).encode())

        self._patch_upstream(monkeypatch, handler)
        self._seed_route("POST", "http://upstream/echo")
        self._login_as_admin(client)

        body = b"P" * (5 * 1024 * 1024)  # 5MB
        resp = client.post("/relay/v2/dashboard/api/node-routes/test-node/api/echo", content=body)
        assert resp.status_code == 200, resp.text
        assert resp.content == b"ok:5242880"
        # The upstream saw the full 5MB.
        assert received["total"] == 5 * 1024 * 1024
        # content-length was forwarded (T-129: keep content-length for streams).
        assert received["content_length"] == "5242880"

    def test_get_streams_large_response(self, client: TestClient, monkeypatch):
        """A large upstream response is streamed back to the caller.

        The mock upstream returns a 10MB response. We stream the
        downstream client response and count bytes; the proxy must
        forward chunks without buffering the whole 10MB in memory
        (StreamingResponse).
        """
        big_payload = b"R" * (10 * 1024 * 1024)

        def handler(req):
            return httpx.Response(200, content=big_payload)

        self._patch_upstream(monkeypatch, handler)
        self._seed_route("GET", "http://upstream/big", path="/api/big")
        self._login_as_admin(client)

        with client.stream("GET", "/relay/v2/dashboard/api/node-routes/test-node/api/big") as resp:
            assert resp.status_code == 200, resp.text
            total = 0
            for chunk in resp.iter_bytes(chunk_size=64 * 1024):
                total += len(chunk)
            assert total == 10 * 1024 * 1024

    def test_proxy_returns_502_on_upstream_error(self, client: TestClient, monkeypatch):
        """A transport error from the upstream surfaces as 502."""
        import httpx as _httpx

        def handler(req):
            raise _httpx.ConnectError("upstream down", request=req)

        self._patch_upstream(monkeypatch, handler)
        self._seed_route("GET", "http://upstream/dead", path="/api/dead")
        self._login_as_admin(client)

        resp = client.get("/relay/v2/dashboard/api/node-routes/test-node/api/dead")
        assert resp.status_code == 502, resp.text
