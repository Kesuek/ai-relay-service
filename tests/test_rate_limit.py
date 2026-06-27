"""Tests for rate limiting on authentication and dashboard endpoints."""

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from relay_server.api.v2.auth import limiter as auth_limiter
from relay_server.api.v2.dashboard import limiter as dashboard_limiter
from relay_server.config import settings
from relay_server.core.auth import generate_secret, hash_secret
from relay_server.core.db import get_conn, init_db
from relay_server.main import app

client = TestClient(app)


def _reset_limiters():
    for limiter in (auth_limiter, dashboard_limiter):
        if hasattr(limiter, "_storage") and limiter._storage is not None:
            limiter._storage.reset()


@pytest.fixture(autouse=True)
def _fresh_db(monkeypatch):
    _reset_limiters()
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        artifacts_dir = Path(tmp) / "artifacts"
        monkeypatch.setattr(settings, "db_path", db_path)
        monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)
        monkeypatch.setattr(settings, "session_secret", "test-secret-for-rate-limiting")
        init_db()
        yield
    _reset_limiters()


def _admin_bootstrap():
    conn = get_conn()
    secret = generate_secret("adm_")
    conn.execute(
        "INSERT OR REPLACE INTO admin_seeds "
        "(seed_id, seed_hash, role, created_at) VALUES (?, ?, ?, ?)",
        ("master", hash_secret(secret), "admin", "2026-01-01T00:00:00+00:00"),
    )
    conn.commit()
    conn.close()
    r = client.post(
        "/relay/v2/auth/register-admin",
        json={
            "node_name": "admin-rate-limit",
            "bootstrap_secret": secret,
            "capabilities": [{"name": "admin", "version": "1.0.0"}],
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["token"]


def test_register_rate_limit_blocks_after_ten_per_minute():
    _admin_bootstrap()

    # First 10 should succeed (or 409 for duplicate names). We vary names to avoid conflicts.
    for i in range(10):
        r = client.post(
            "/relay/v2/auth/register",
            json={
                "node_name": f"node-{i}",
                "capabilities": [{"name": "test", "version": "1.0.0"}],
                "role": "service",
            },
        )
        assert r.status_code in (200, 409), r.text

    # 11th request from the same IP should be rate limited.
    r = client.post(
        "/relay/v2/auth/register",
        json={
            "node_name": "node-overflow",
            "capabilities": [{"name": "test", "version": "1.0.0"}],
            "role": "service",
        },
    )
    assert r.status_code == 429
    assert r.json()["detail"] == "Rate limit exceeded"


def test_dashboard_login_rate_limit_blocks_after_five_per_minute():
    _admin_bootstrap()

    for i in range(5):
        r = client.post(
            "/relay/v2/dashboard/login",
            data={"mode": "user", "username": "admin", "password": "wrong"},
        )
        assert r.status_code in (200, 303, 307), r.text

    r = client.post(
        "/relay/v2/dashboard/login",
        data={"mode": "user", "username": "admin", "password": "wrong"},
    )
    assert r.status_code == 429
    assert r.json()["detail"] == "Rate limit exceeded"


def test_register_admin_rate_limit_blocks_after_five_per_minute():
    for i in range(5):
        secret = generate_secret("adm_")
        conn = get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO admin_seeds "
            "(seed_id, seed_hash, role, created_at) VALUES (?, ?, ?, ?)",
            (f"master-{i}", hash_secret(secret), "admin", "2026-01-01T00:00:00+00:00"),
        )
        conn.commit()
        conn.close()
        r = client.post(
            "/relay/v2/auth/register-admin",
            json={
                "node_name": f"admin-{i}",
                "bootstrap_secret": secret,
                "capabilities": [{"name": "admin", "version": "1.0.0"}],
            },
        )
        assert r.status_code in (200, 401), r.text

    # 6th request from the same IP should be rate limited.
    r = client.post(
        "/relay/v2/auth/register-admin",
        json={
            "node_name": "admin-overflow",
            "bootstrap_secret": "invalid",
            "capabilities": [{"name": "admin", "version": "1.0.0"}],
        },
    )
    assert r.status_code == 429
    assert r.json()["detail"] == "Rate limit exceeded"
