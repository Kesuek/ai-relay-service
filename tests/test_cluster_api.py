"""Tests for the public cluster portal API (Phase 20 — T-044)."""

import json
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from relay_server.config import settings
from relay_server.core.db import get_conn, init_db, q
from relay_server.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _fresh_db(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        artifacts_dir = Path(tmp) / "artifacts"
        monkeypatch.setattr(settings, "db_path", db_path)
        monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)
        monkeypatch.setattr(settings, "session_secret", "test-secret-for-cluster-tests-1234567890")
        init_db()
        _seed_data()
        yield


def _seed_data():
    conn = get_conn()
    now = "2026-07-29T20:00:00+00:00"
    conn.execute(
        q("INSERT INTO nodes (node_id, node_name, endpoint, capabilities, status, role, load, queue_depth, last_seen, registered_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", ("node1", "felix-cyberfox", "http://10.0.0.1:8788", json.dumps([{"name": "chat.ai"}, {"name": "code.ai"}]), "online", "worker", 62.0, 1, now, now)),
    )
    conn.execute(
        q("INSERT INTO nodes (node_id, node_name, endpoint, capabilities, status, role, load, queue_depth, last_seen, registered_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", ("node2", "m4-macmini", "http://10.0.0.2:8788", json.dumps([{"name": "image.gen.mflux"}]), "busy", "worker", 91.0, 3, now, now)),
    )
    conn.execute(
        q("INSERT INTO nodes (node_id, node_name, endpoint, capabilities, status, role, load, queue_depth, last_seen, registered_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", ("__dashboard_admin__", "Dashboard Admin", "", "[]", "online", "admin", 0.0, 0, now, now)),
    )
    conn.execute(
        q("INSERT INTO tasks (task_id, task_name, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)", ("T-001", "Test task", "completed", now, now)),
    )
    conn.execute(
        q("INSERT INTO task_stages (stage_id, task_id, stage_name, capability, status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)", ("S-001", "T-001", "default", "chat.ai", "completed", now, now)),
    )
    conn.execute(
        q("INSERT INTO artifacts (artifact_id, name, mime_type, size_bytes, storage_path, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)", ("art-001", "test.png", "image/png", 1024, "/tmp/test.png", now)),
    )
    conn.execute(
        q("INSERT INTO users (user_id, username, password_hash, is_active, status, created_at) VALUES (?, ?, ?, ?, ?, ?)", ("u-001", "ronny", "$2b$12$dummyhashdummyhashdummyhashdummyhashdummyhashdummyhash", 1, "active", now)),
    )
    # Groups are seeded by init_db() — just add the user-group link.
    conn.execute(
        q("INSERT OR IGNORE INTO user_groups (user_id, group_id, granted_at) VALUES (?, "
        "(SELECT group_id FROM groups WHERE group_name = 'admin'), ?)", ("u-001", now)),
    )
    conn.commit()
    conn.close()


class TestClusterOverview:
    def test_overview_public(self):
        r = client.get("/relay/v2/cluster/overview")
        assert r.status_code == 200
        data = r.json()
        assert "summary" in data
        assert "nodes" in data
        assert "activity" in data
        assert data["summary"]["total_nodes"] == 2  # excludes __dashboard_admin__
        assert data["summary"]["online_nodes"] == 1

    def test_overview_summary_counts(self):
        r = client.get("/relay/v2/cluster/overview")
        data = r.json()
        s = data["summary"]
        assert s["total_tasks"] == 1
        assert s["active_stages"] == 0
        assert s["total_artifacts"] == 1

    def test_overview_excludes_admin_node(self):
        r = client.get("/relay/v2/cluster/overview")
        node_ids = [n["node_id"] for n in r.json()["nodes"]]
        assert "__dashboard_admin__" not in node_ids


class TestClusterNodes:
    def test_nodes_list_public(self):
        r = client.get("/relay/v2/cluster/nodes")
        assert r.status_code == 200
        nodes = r.json()["nodes"]
        assert len(nodes) == 2
        names = [n["node_name"] for n in nodes]
        assert "felix-cyberfox" in names
        assert "m4-macmini" in names

    def test_node_profile_public(self):
        r = client.get("/relay/v2/cluster/nodes/node1")
        assert r.status_code == 200
        profile = r.json()
        assert profile["node_name"] == "felix-cyberfox"
        assert profile["status"] == "online"
        assert profile["load"] == 62.0
        assert "capability_names" in profile
        assert "recent_tasks" in profile

    def test_node_profile_not_found(self):
        r = client.get("/relay/v2/cluster/nodes/nonexistent")
        assert r.status_code == 404

    def test_node_profile_admin_node_404(self):
        r = client.get("/relay/v2/cluster/nodes/__dashboard_admin__")
        assert r.status_code == 404


class TestClusterUsers:
    def test_users_list_public(self):
        r = client.get("/relay/v2/cluster/users")
        assert r.status_code == 200
        users = r.json()["users"]
        assert len(users) == 1
        assert users[0]["username"] == "ronny"

    def test_user_profile_public(self):
        r = client.get("/relay/v2/cluster/users/u-001")
        assert r.status_code == 200
        profile = r.json()
        assert profile["username"] == "ronny"
        assert profile["role"] == "admin"

    def test_user_profile_not_found(self):
        r = client.get("/relay/v2/cluster/users/nonexistent")
        assert r.status_code == 404


class TestClusterActivity:
    def test_activity_public(self):
        r = client.get("/relay/v2/cluster/activity")
        assert r.status_code == 200
        data = r.json()
        assert "events" in data
