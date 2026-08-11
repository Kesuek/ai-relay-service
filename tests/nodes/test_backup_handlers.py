"""Tests for the storage node backup handlers (T-130/T-131/T-132)."""
from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

from nodes.common.handler_runner import run_handler

HANDLERS = Path(__file__).resolve().parents[2] / "docker" / "storage" / "handlers"


def _stage(payload=None):
    return {
        "stage_id": "st1",
        "task_id": "tk1",
        "capability": "backup.create",
        "payload": payload or {},
    }


def _ctx(storage_path: Path, **extra) -> dict:
    env = {
        "RELAY_NODE_ID": "node-abc",
        "RELAY_BASE_URL": "http://relay.test",
        "RELAY_TOKEN_FILE": str(storage_path / "token"),
    }
    env.update(extra)
    return env


def _err_text(result: dict) -> str:
    if result.get("error", "").startswith("handler exited"):
        stdout = result.get("stdout", "")
        try:
            parsed = json.loads(stdout)
            return parsed.get("error", stdout)
        except (json.JSONDecodeError, TypeError):
            return stdout or result["error"]
    return result.get("error", "")


def _run(handler_name: str, payload: dict, storage_path: Path, **env) -> dict:
    handler = f"{sys.executable} {HANDLERS / handler_name}"
    ctx = _ctx(storage_path)
    old = os.environ.get("RELAY_STORAGE_PATH")
    os.environ["RELAY_STORAGE_PATH"] = str(storage_path)
    prev_extras = {k: os.environ.get(k) for k in env}
    os.environ.update({k: str(v) for k, v in env.items()})
    try:
        return run_handler(handler, _stage(payload), context=ctx, timeout=30)
    finally:
        if old is None:
            os.environ.pop("RELAY_STORAGE_PATH", None)
        else:
            os.environ["RELAY_STORAGE_PATH"] = old
        for k, v in prev_extras.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class TestBackupCommon:
    def test_manifest_roundtrip(self, tmp_path: Path):
        # backup_common is imported by the handlers; exercise via backup_create
        result = _run(
            "backup_create.py",
            {"source": "projects", "type": "full", "data_base64": "aGVsbG8="},
            tmp_path,
        )
        assert result["status"] == "created", result
        backup_id = result["backup_id"]
        manifest_path = tmp_path / "backups" / backup_id / "manifest.json"
        assert manifest_path.is_file()
        manifest = json.loads(manifest_path.read_text())
        assert manifest["backup_id"] == backup_id
        assert manifest["source"] == "projects"
        assert manifest["type"] == "full"
        assert manifest["status"] == "active"
        assert manifest["created_at"]
        assert manifest["size_bytes"] == 5


class TestBackupCreate:
    def test_create_full_inline(self, tmp_path: Path):
        result = _run(
            "backup_create.py",
            {"source": "projects", "type": "full", "data_base64": "aGVsbG8="},
            tmp_path,
        )
        assert result["status"] == "created", result
        backup_id = result["backup_id"]
        assert backup_id.startswith("bk_")
        # data file written next to manifest
        data_file = tmp_path / "backups" / backup_id / "data.bin"
        assert data_file.read_bytes() == b"hello"
        manifest = json.loads((tmp_path / "backups" / backup_id / "manifest.json").read_text())
        assert manifest["size_bytes"] == 5

    def test_create_incremental_requires_base(self, tmp_path: Path):
        result = _run(
            "backup_create.py",
            {"source": "projects", "type": "incremental", "data_base64": "aGVsbG8="},
            tmp_path,
        )
        assert "base_backup_id" in _err_text(result).lower()

    def test_create_incremental_with_base(self, tmp_path: Path):
        # create a full backup first
        full = _run(
            "backup_create.py",
            {"source": "projects", "type": "full", "data_base64": "aGVsbG8="},
            tmp_path,
        )
        base_id = full["backup_id"]
        inc = _run(
            "backup_create.py",
            {"source": "projects", "type": "incremental", "base_backup_id": base_id, "data_base64": "d29ybGQ="},
            tmp_path,
        )
        assert inc["status"] == "created", inc
        manifest = json.loads((tmp_path / "backups" / inc["backup_id"] / "manifest.json").read_text())
        assert manifest["base_backup_id"] == base_id

    def test_create_incremental_missing_base(self, tmp_path: Path):
        result = _run(
            "backup_create.py",
            {"source": "projects", "type": "incremental", "base_backup_id": "bk_deadbeef", "data_base64": "aGVsbG8="},
            tmp_path,
        )
        assert "base backup not found" in _err_text(result).lower()

    def test_create_missing_source(self, tmp_path: Path):
        result = _run("backup_create.py", {"type": "full", "data_base64": "aGVsbG8="}, tmp_path)
        assert "source" in _err_text(result).lower()


class TestBackupList:
    def test_list_empty(self, tmp_path: Path):
        result = _run("backup_list.py", {}, tmp_path)
        assert result["status"] == "listed"
        assert result["count"] == 0
        assert result["backups"] == []

    def test_list_after_create(self, tmp_path: Path):
        _run("backup_create.py", {"source": "projects", "type": "full", "data_base64": "aGVsbG8="}, tmp_path)
        result = _run("backup_list.py", {}, tmp_path)
        assert result["count"] == 1
        assert result["backups"][0]["source"] == "projects"
        assert result["backups"][0]["type"] == "full"

    def test_list_filter_source(self, tmp_path: Path):
        _run("backup_create.py", {"source": "projects", "type": "full", "data_base64": "aGVsbG8="}, tmp_path)
        _run("backup_create.py", {"source": "photos", "type": "full", "data_base64": "aGVsbG8="}, tmp_path)
        result = _run("backup_list.py", {"source": "photos"}, tmp_path)
        assert result["count"] == 1
        assert result["backups"][0]["source"] == "photos"


class TestBackupInfo:
    def test_info_returns_manifest(self, tmp_path: Path):
        created = _run("backup_create.py", {"source": "projects", "type": "full", "data_base64": "aGVsbG8="}, tmp_path)
        backup_id = created["backup_id"]
        result = _run("backup_info.py", {"backup_id": backup_id}, tmp_path)
        assert result["status"] == "info"
        assert result["backup_id"] == backup_id
        assert result["source"] == "projects"
        assert result["type"] == "full"
        assert result["size_bytes"] == 5

    def test_info_missing(self, tmp_path: Path):
        result = _run("backup_info.py", {"backup_id": "bk_deadbeef"}, tmp_path)
        assert "not found" in _err_text(result).lower()


class TestBackupRestore:
    def test_restore_returns_data(self, tmp_path: Path):
        created = _run("backup_create.py", {"source": "projects", "type": "full", "data_base64": "aGVsbG8="}, tmp_path)
        backup_id = created["backup_id"]
        result = _run("backup_restore.py", {"backup_id": backup_id}, tmp_path)
        assert result["status"] == "restored"
        assert base64.b64decode(result["data_base64"]) == b"hello"
        assert result["size_bytes"] == 5

    def test_restore_missing(self, tmp_path: Path):
        result = _run("backup_restore.py", {"backup_id": "bk_deadbeef"}, tmp_path)
        assert "not found" in _err_text(result).lower()


class TestBackupDelete:
    def test_delete_marks_deleted(self, tmp_path: Path):
        created = _run("backup_create.py", {"source": "projects", "type": "full", "data_base64": "aGVsbG8="}, tmp_path)
        backup_id = created["backup_id"]
        result = _run("backup_delete.py", {"backup_id": backup_id}, tmp_path)
        assert result["status"] == "deleted"
        manifest = json.loads((tmp_path / "backups" / backup_id / "manifest.json").read_text())
        assert manifest["status"] == "deleted"

    def test_delete_missing(self, tmp_path: Path):
        result = _run("backup_delete.py", {"backup_id": "bk_deadbeef"}, tmp_path)
        assert "not found" in _err_text(result).lower()


class TestBackupRetention:
    def test_keep_last(self, tmp_path: Path):
        # create 3 backups, keep_last=2 -> oldest marked deleted
        ids = []
        for _ in range(3):
            r = _run("backup_create.py", {"source": "projects", "type": "full", "data_base64": "aGVsbG8="}, tmp_path)
            ids.append(r["backup_id"])
        result = _run("backup_retention.py", {"source": "projects", "policy": {"keep_last": 2}}, tmp_path)
        assert result["status"] == "applied"
        assert result["deleted"] == [ids[0]]
        m0 = json.loads((tmp_path / "backups" / ids[0] / "manifest.json").read_text())
        m1 = json.loads((tmp_path / "backups" / ids[1] / "manifest.json").read_text())
        assert m0["status"] == "deleted"
        assert m1["status"] == "active"

    def test_max_age_days(self, tmp_path: Path):
        r = _run("backup_create.py", {"source": "projects", "type": "full", "data_base64": "aGVsbG8="}, tmp_path)
        backup_id = r["backup_id"]
        mf = tmp_path / "backups" / backup_id / "manifest.json"
        m = json.loads(mf.read_text())
        from datetime import datetime, timedelta, timezone
        old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat().replace("+00:00", "Z")
        m["created_at"] = old
        mf.write_text(json.dumps(m))
        result = _run("backup_retention.py", {"source": "projects", "policy": {"max_age_days": 7}}, tmp_path)
        assert result["deleted"] == [backup_id]

    def test_retention_skips_other_sources(self, tmp_path: Path):
        _run("backup_create.py", {"source": "projects", "type": "full", "data_base64": "aGVsbG8="}, tmp_path)
        _run("backup_create.py", {"source": "projects", "type": "full", "data_base64": "aGVsbG8="}, tmp_path)
        _run("backup_create.py", {"source": "photos", "type": "full", "data_base64": "aGVsbG8="}, tmp_path)
        result = _run("backup_retention.py", {"source": "projects", "policy": {"keep_last": 1}}, tmp_path)
        # the older projects backup is deleted (keep_last=1 keeps the newest)
        assert len(result["deleted"]) == 1
        # photos untouched
        photos = _run("backup_list.py", {"source": "photos"}, tmp_path)
        assert photos["count"] == 1


class TestRetentionWatchdog:
    def test_watchdog_applies_policies(self, tmp_path: Path):
        for _ in range(3):
            _run("backup_create.py", {"source": "projects", "type": "full", "data_base64": "aGVsbG8="}, tmp_path)
        cfg = tmp_path / "retention.yaml"
        cfg.write_text("projects:\n  keep_last: 2\n")
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "retention_watchdog", str(HANDLERS.parent / "retention_watchdog.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.apply_policies(str(cfg), str(tmp_path))
        result = _run("backup_list.py", {"source": "projects"}, tmp_path)
        assert result["count"] == 2