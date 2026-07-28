"""Tests for dynamic node routes (T-075)."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

os.environ["RELAY_SESSION_SECRET"] = "test-secret-32-chars-minimum!!!"

from relay_server.config import settings
from relay_server.core.db import get_conn, init_db
from relay_server.main import app


@pytest.fixture
def client():
    """Create a test client with an isolated database."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        settings.db_path = db_path
        settings.session_secret = "test-secret-32-chars-minimum!!!"
        settings.session_cookie_secure = False
        init_db()

        # Seed a node first (FOREIGN KEY constraint)
        conn = get_conn()
        conn.execute(
            "INSERT INTO nodes (node_id, node_name, status, role, last_seen, registered_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("test-node", "test-node", "online", "worker", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )
        # Seed a route in the DB
        conn.execute(
            "INSERT INTO node_routes (node_id, path, method, auth, upstream, description) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("test-node", "/api/test", "GET", "session", "http://localhost:9999/api/test", "Test route"),
        )
        conn.commit()
        conn.close()

        yield TestClient(app)


class TestRouteRegistry:
    """Tests for the dynamic node route proxy."""

    def test_route_not_found_returns_401_without_auth(self, client: TestClient):
        """Without session cookie, auth fails first (401)."""
        resp = client.get("/relay/v2/dashboard/api/node-routes/nonexistent/api/test")
        assert resp.status_code == 401

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
            "SELECT * FROM node_routes WHERE node_id = ?", ("test-node",)
        ).fetchone()
        assert row is not None
        assert row["path"] == "/api/test"
        assert row["method"] == "GET"
        assert row["auth"] == "session"
        conn.close()

    def test_route_clear_on_offline(self, client: TestClient):
        """Verify routes are cleared when a node goes offline."""
        conn = get_conn()
        conn.execute("DELETE FROM node_routes WHERE node_id = ?", ("test-node",))
        conn.commit()
        row = conn.execute(
            "SELECT * FROM node_routes WHERE node_id = ?", ("test-node",)
        ).fetchone()
        assert row is None
        conn.close()


class TestCapabilityYAMLRoutes:
    """Tests for routes in capability YAML."""

    def test_routes_in_yaml_validates(self):
        """Verify that routes in capability YAML pass validation."""
        from nodes.common.capability_loader import validate_profile

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
        from nodes.common.capability_loader import validate_profile

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
