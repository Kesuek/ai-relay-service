"""Tests for the database layer — secret redaction in audit logs (T-024)."""

import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("RELAY_DB_PATH", "")
os.environ.setdefault("RELAY_SESSION_SECRET", "test-session-secret-do-not-use-in-production")

from relay_server.config import settings  # noqa: E402
from relay_server.core.db import _redact_secrets, get_conn, init_db, log_audit_event  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    """Use a temporary database for each test."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        settings.db_path = db_path
        init_db()
        yield


# --- _redact_secrets unit tests --------------------------------------------


def test_redact_none_passthrough():
    assert _redact_secrets(None) is None


def test_redact_empty_string():
    assert _redact_secrets("") == ""


def test_redact_runtime_token():
    out = _redact_secrets("token=rt_abcdefghijklmnop1234567890test")
    assert "rt_abcdefghijklmnop" not in out
    assert "[REDACTED]" in out


def test_redact_registration_secret():
    out = _redact_secrets("rs_abcdefghijklmnop1234567890test")
    assert "rs_abcdefghijklmnop" not in out
    assert out == "[REDACTED]"


def test_redact_bearer_header():
    out = _redact_secrets("Authorization: Bearer rt_sometokenvalue1234567890")
    assert "rt_sometokenvalue" not in out
    assert "[REDACTED]" in out


def test_redact_password_keyvalue():
    out = _redact_secrets("password=hunter2")
    assert "hunter2" not in out
    assert "[REDACTED]" in out


def test_redact_preserves_normal_details():
    out = _redact_secrets("role=admin user=alice")
    assert out == "role=admin user=alice"


def test_redact_multiple_secrets_in_one_string():
    out = _redact_secrets("old=rt_abcdefghijklmnop1234567890 new=rs_zyxwvutsrqponm1234567890")
    assert "rt_abcdef" not in out
    assert "rs_zyxwvuts" not in out
    assert out.count("[REDACTED]") == 2


# --- log_audit_event integration test --------------------------------------


def test_audit_event_redacts_secrets_before_persisting():
    log_audit_event(
        actor_id="node_ABCD1234",
        action="test.action",
        resource_type="node",
        resource_id="ABCD1234",
        details="token=rt_supersecrettoken1234567890ab role=admin",
    )

    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT details FROM audit_logs WHERE action = ? ORDER BY created_at DESC LIMIT 1",
            ("test.action",),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    details = row["details"]
    assert "rt_supersecrettoken" not in details
    assert "[REDACTED]" in details
    assert "role=admin" in details