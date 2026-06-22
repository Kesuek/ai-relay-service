"""Tests for the recovery CLI."""

import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ["RELAY_DB_PATH"] = ""

from relay_server.config import settings
from relay_server.core.auth import init_master_seed
from relay_server.main import app
from relay_server.core.db import init_db_for_path
from relay_server.core.users import create_user, list_users, set_user_active


def test_recovery_cli_deactivates_admin_and_re_enables_seed_login():
    """Recovery CLI deactivates human admins so the master seed can log in again."""
    from relay_server.cli import main
    from relay_server.api.v2.dashboard import has_admin_user

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        settings.db_path = db_path
        settings.session_secret = "test-session-secret-do-not-use-in-production"
        settings.session_cookie_secure = False
        init_db_for_path(db_path)

        # Bootstrap: create master seed.
        seed = init_master_seed()
        assert seed

        # Create a human admin; master-seed login should now be disabled.
        create_user("locked-out-admin", "very-strong-passphrase-42", group_names=["admin"], force_password_change=False)
        assert has_admin_user() is True

        # Run recovery CLI with --all.
        assert main(["--db-path", str(db_path), "enable-recovery", "--all"]) == 0

        # Admin is deactivated.
        admins = [u for u in list_users() if u["is_active"] and "admin" in u.get("groups", [])]
        assert len(admins) == 0

        # Now seed login should work again.
        client = TestClient(app)
        r = client.post(
            "/relay/v2/dashboard/login",
            data={"mode": "seed", "seed": seed},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert r.cookies.get("relay_user")

        # Cleanup side-effect session state.
        set_user_active(list_users()[0]["user_id"], True)
