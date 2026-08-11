"""Tests for the storage node backup handlers (T-130/T-131/T-132)."""
from __future__ import annotations

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