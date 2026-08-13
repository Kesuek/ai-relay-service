"""Tests for the ``node-cli file`` subcommand (T-164).

Covers ``file send`` (inline / artifact / bridge mode selection) and
``file get`` (inline / bridge). The transfer-ladder choice is driven by
the server's ``transfer-config`` + the capability's ``upload_modes``.
We mock the RelayClient HTTP methods so no network is needed, and stand
up a tiny local HTTP server for the actual bridge streaming.
"""

from __future__ import annotations

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from nodes.common import node_cli as cli
from nodes.common import node_config as cl
from nodes.common import node_utils
from nodes.common.relay_client import RelayClient

# ---------------------------------------------------------------------------
# Fixtures — mirror test_cli_bridge.py
# ---------------------------------------------------------------------------


@pytest.fixture()
def isolated_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    base = tmp_path / "relay"
    profiles_dir = base / "profiles.d"
    active = base / "node.yaml"
    active_name = base / "node.profile"

    monkeypatch.setattr(cl, "BASE_DIR", base)
    monkeypatch.setattr(cl, "PROFILES_DIR", profiles_dir)
    monkeypatch.setattr(cl, "ACTIVE_PATH", active)
    monkeypatch.setattr(cl, "ACTIVE_PROFILE_NAME_PATH", active_name)
    monkeypatch.setattr(cl._active_cache, "path", active)

    monkeypatch.setattr(cli, "BASE_DIR", base)
    monkeypatch.setattr(cli, "PROFILES_DIR", profiles_dir)
    monkeypatch.setattr(cli, "ACTIVE_PATH", active)
    monkeypatch.setattr(cli, "PID_PATH", base / "node-cli.pid")
    monkeypatch.setattr(cli, "LOG_PATH", base / "node-cli.log")
    monkeypatch.setattr(cli, "STATUS_PATH", base / "worker_status.json")

    monkeypatch.setattr(node_utils, "BASE_DIR", base)
    monkeypatch.setattr(node_utils, "CONFIG_PATH", base / "relay_config.json")
    monkeypatch.setattr(node_utils, "META_PATH", base / "ai-relay-agent.json")
    monkeypatch.setattr(node_utils, "TOKEN_PATH", base / "ai-relay-agent.token")
    monkeypatch.setattr(node_utils, "STATUS_PATH", base / "worker_status.json")

    profiles_dir.mkdir(parents=True, exist_ok=True)
    return base


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content + "\n", encoding="utf-8")
    return path


def _wire_client(monkeypatch: pytest.MonkeyPatch, isolated_paths: Path, client: RelayClient):
    monkeypatch.setattr(
        cli, "load_meta", lambda: {"node_id": "n1", "base_url": "http://relay.test"}
    )
    monkeypatch.setattr(
        cli, "_effective_config", lambda: {"base_url": "http://relay.test", "request_timeout": 5}
    )
    monkeypatch.setattr(cli, "RelayClient", lambda meta, cfg: client)


def _make_client(isolated_paths: Path) -> RelayClient:
    _write(
        isolated_paths / "relay_config.json",
        json.dumps({"base_url": "http://relay:8788", "request_timeout": 10}),
    )
    _write(
        isolated_paths / "ai-relay-agent.json",
        json.dumps({"node_id": "n1", "registration_secret": "rs_abc"}),
    )
    _write(isolated_paths / "ai-relay-agent.token", "rt_test")
    meta = node_utils.load_meta()
    cfg = node_utils.load_config()
    return RelayClient(meta, cfg)


# ---------------------------------------------------------------------------
# Fake bridge server
# ---------------------------------------------------------------------------


class _BridgeHandler(BaseHTTPRequestHandler):
    uploaded: bytes = b""
    download_body: bytes = b"payload-from-storage"
    download_filename: str = "data.bin"
    seen_auth: str | None = None

    def log_message(self, format, *args):  # noqa: A002 — silence
        pass

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        type(self).uploaded = body
        type(self).seen_auth = self.headers.get("Authorization")
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):  # noqa: N802
        type(self).seen_auth = self.headers.get("Authorization")
        body = type(self).download_body
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Filename", type(self).download_filename)
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def bridge_server():
    _BridgeHandler.uploaded = b""
    _BridgeHandler.download_body = b"payload-from-storage"
    _BridgeHandler.download_filename = "data.bin"
    _BridgeHandler.seen_auth = None
    server = HTTPServer(("127.0.0.1", 0), _BridgeHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield server
    server.shutdown()


# ---------------------------------------------------------------------------
# Transfer config + capability-detail mocking
# ---------------------------------------------------------------------------


_TRANSFER_CFG = {
    "max_inline_bytes": 5 * 1024 * 1024,      # 5 MB
    "max_artifact_bytes": 50 * 1024 * 1024,   # 50 MB
    "max_payload_bytes": 10 * 1024 * 1024,
}


def _mock_config_and_cap(
    monkeypatch,
    upload_modes: list[str],
    input_schema_fields: dict | None = None,
):
    """Mock get_transfer_config + get_capability_detail."""
    schema = {"fields": input_schema_fields or {"path": {}}}

    def fake_cfg(self):
        return dict(_TRANSFER_CFG)

    def fake_cap(self, name):
        return {
            "name": name,
            "type": "native",
            "description": "test",
            "version": "1.0.0",
            "available": True,
            "input_schema": schema,
            "upload_modes": upload_modes,
            "nodes": [],
        }

    monkeypatch.setattr(RelayClient, "get_transfer_config", fake_cfg)
    monkeypatch.setattr(RelayClient, "get_capability_detail", fake_cap)


def _mock_submit_and_wait(monkeypatch, result: dict, captured: dict | None = None):
    """Mock submit_simple_task + get_task so _wait_for_result returns ``result``."""

    def fake_submit(self, capability, payload, *, name="", priority=0, owner_node_id=None):
        if captured is not None:
            captured.update(capability=capability, payload=payload)
        return {"task_id": "tsk_file"}

    def fake_get(self, task_id):
        return {
            "task": {"task_id": task_id, "status": "completed"},
            "stages": [{"status": "completed", "result": result}],
            "notes": [], "artifacts": [],
        }

    monkeypatch.setattr(RelayClient, "submit_simple_task", fake_submit)
    monkeypatch.setattr(RelayClient, "get_task", fake_get)


# ---------------------------------------------------------------------------
# file send
# ---------------------------------------------------------------------------


class TestFileSend:
    def test_inline_small_file(self, isolated_paths, monkeypatch, capsys):
        client = _make_client(isolated_paths)
        _mock_config_and_cap(monkeypatch, ["inline", "artifact", "bridge"])
        captured: dict = {}
        _mock_submit_and_wait(monkeypatch, {"status": "stored"}, captured)
        _wire_client(monkeypatch, isolated_paths, client)

        src = isolated_paths / "small.txt"
        src.write_bytes(b"hello")
        rc = cli.main(["--json", "file", "send", str(src), "--cap", "storage.store"])
        assert rc == 0
        assert captured["capability"] == "storage.store"
        assert "data_base64" in captured["payload"]
        assert "artifact_id" not in captured["payload"]
        assert "storage_ref" not in captured["payload"]
        out = json.loads(capsys.readouterr().out)
        assert out["mode"] == "inline"
        assert out["size_bytes"] == 5

    def test_artifact_medium_file(self, isolated_paths, monkeypatch, capsys):
        client = _make_client(isolated_paths)
        _mock_config_and_cap(monkeypatch, ["inline", "artifact", "bridge"])
        captured: dict = {}
        _mock_submit_and_wait(monkeypatch, {"status": "stored"}, captured)
        # Mock the artifact upload.
        monkeypatch.setattr(
            RelayClient, "upload_artifact",
            lambda self, fp, name=None, task_id=None, stage_id=None: {
                "artifact_id": "art_123", "name": name, "size_bytes": 8 * 1024 * 1024,
            },
        )
        _wire_client(monkeypatch, isolated_paths, client)

        src = isolated_paths / "medium.bin"
        src.write_bytes(b"x" * (8 * 1024 * 1024))  # 8 MB — above inline (5), below artifact (50)
        rc = cli.main(["--json", "file", "send", str(src), "--cap", "storage.store"])
        assert rc == 0
        assert captured["payload"].get("artifact_id") == "art_123"
        assert "data_base64" not in captured["payload"]
        out = json.loads(capsys.readouterr().out)
        assert out["mode"] == "artifact"
        assert out["artifact_id"] == "art_123"

    def test_bridge_large_file(self, isolated_paths, monkeypatch, capsys, bridge_server):
        client = _make_client(isolated_paths)
        _mock_config_and_cap(monkeypatch, ["inline", "artifact", "bridge"])
        captured: dict = {}
        url = f"http://127.0.0.1:{bridge_server.server_port}/upload/ch_x"
        _mock_submit_and_wait(
            monkeypatch,
            {"status": "open", "upload_url": url, "channel_id": "ch_x"},
            captured,
        )
        _wire_client(monkeypatch, isolated_paths, client)

        src = isolated_paths / "large.bin"
        src.write_bytes(b"x" * (60 * 1024 * 1024))  # 60 MB — above artifact (50)
        rc = cli.main(["--json", "file", "send", str(src), "--cap", "storage.store"])
        assert rc == 0
        # The storage_ref payload was submitted to storage.store.
        assert captured["payload"].get("storage_ref") == {
            "type": "channel", "id": "ch_x", "filename": "large.bin",
        }
        assert _BridgeHandler.uploaded == b"x" * (60 * 1024 * 1024)
        out = json.loads(capsys.readouterr().out)
        assert out["mode"] == "bridge"
        assert out["storage_ref"]["id"] == "ch_x"

    def test_capability_limit_narrows_inline(self, isolated_paths, monkeypatch, capsys):
        """Cap allows only inline up to 3 MB, file is 4 MB → artifact."""
        client = _make_client(isolated_paths)
        _mock_config_and_cap(monkeypatch, ["inline", "artifact"])
        # Override the transfer config so inline-max is 3 MB for this test.
        monkeypatch.setattr(
            RelayClient, "get_transfer_config",
            lambda self: {
                "max_inline_bytes": 3 * 1024 * 1024,
                "max_artifact_bytes": 50 * 1024 * 1024,
                "max_payload_bytes": 10 * 1024 * 1024,
            },
        )
        captured: dict = {}
        _mock_submit_and_wait(monkeypatch, {"status": "stored"}, captured)
        monkeypatch.setattr(
            RelayClient, "upload_artifact",
            lambda self, fp, name=None, task_id=None, stage_id=None: {
                "artifact_id": "art_z", "name": name, "size_bytes": 4 * 1024 * 1024,
            },
        )
        _wire_client(monkeypatch, isolated_paths, client)

        src = isolated_paths / "mid.bin"
        src.write_bytes(b"x" * (4 * 1024 * 1024))  # 4 MB — above cap inline (3), below artifact
        rc = cli.main(["--json", "file", "send", str(src), "--cap", "storage.store"])
        assert rc == 0
        assert "artifact_id" in captured["payload"]
        out = json.loads(capsys.readouterr().out)
        assert out["mode"] == "artifact"

    def test_force_override(self, isolated_paths, monkeypatch, capsys):
        """--force artifact on a small file skips inline."""
        client = _make_client(isolated_paths)
        _mock_config_and_cap(monkeypatch, ["inline", "artifact", "bridge"])
        captured: dict = {}
        _mock_submit_and_wait(monkeypatch, {"status": "stored"}, captured)
        monkeypatch.setattr(
            RelayClient, "upload_artifact",
            lambda self, fp, name=None, task_id=None, stage_id=None: {
                "artifact_id": "art_f", "name": name, "size_bytes": 5,
            },
        )
        _wire_client(monkeypatch, isolated_paths, client)

        src = isolated_paths / "tiny.txt"
        src.write_bytes(b"hi")
        rc = cli.main(["--json", "file", "send", str(src), "--cap", "storage.store",
                       "--force", "artifact"])
        assert rc == 0
        assert captured["payload"].get("artifact_id") == "art_f"
        out = json.loads(capsys.readouterr().out)
        assert out["mode"] == "artifact"

    def test_force_unsupported_mode_errors(self, isolated_paths, monkeypatch, capsys):
        client = _make_client(isolated_paths)
        _mock_config_and_cap(monkeypatch, ["inline"])  # no artifact
        _wire_client(monkeypatch, isolated_paths, client)

        src = isolated_paths / "tiny.txt"
        src.write_bytes(b"hi")
        rc = cli.main(["--json", "file", "send", str(src), "--cap", "storage.store",
                       "--force", "artifact"])
        assert rc != 0
        err = capsys.readouterr().err
        assert "not supported" in err.lower() or "artifact" in err.lower()

    def test_file_too_big_for_supported_modes(self, isolated_paths, monkeypatch, capsys):
        """File exceeds all supported modes and bridge is not available."""
        client = _make_client(isolated_paths)
        _mock_config_and_cap(monkeypatch, ["inline"])  # no artifact, no bridge
        _wire_client(monkeypatch, isolated_paths, client)

        src = isolated_paths / "big.bin"
        src.write_bytes(b"x" * (60 * 1024 * 1024))  # 60 MB, only inline (5) supported
        rc = cli.main(["file", "send", str(src), "--cap", "storage.store"])
        assert rc != 0
        err = capsys.readouterr().err
        assert "too big" in err.lower()

    def test_missing_file(self, isolated_paths, monkeypatch, capsys):
        client = _make_client(isolated_paths)
        _mock_config_and_cap(monkeypatch, ["inline", "artifact", "bridge"])
        _wire_client(monkeypatch, isolated_paths, client)
        rc = cli.main(["--json", "file", "send", str(isolated_paths / "nope.bin"), "--cap", "storage.store"])
        assert rc == 2
        assert "file not found" in capsys.readouterr().err.lower()


# ---------------------------------------------------------------------------
# file get
# ---------------------------------------------------------------------------


class TestFileGet:
    def test_get_inline_storage_fetch(self, isolated_paths, monkeypatch, capsys):
        client = _make_client(isolated_paths)
        _mock_config_and_cap(
            monkeypatch,
            ["inline", "bridge"],
            input_schema_fields={"path": {"type": "string"}},
        )
        payload_bytes = b"fetched-content"
        _mock_submit_and_wait(
            monkeypatch,
            {"status": "ok", "data_base64": base64.b64encode(payload_bytes).decode()},
        )
        _wire_client(monkeypatch, isolated_paths, client)

        out = isolated_paths / "out.txt"
        rc = cli.main([
            "--json", "file", "get", "some/path", "--cap", "storage.fetch", "-o", str(out),
        ])
        assert rc == 0
        assert out.read_bytes() == payload_bytes
        result = json.loads(capsys.readouterr().out)
        assert result["mode"] == "inline"

    def test_get_bridge_backup_restore(self, isolated_paths, monkeypatch, capsys, bridge_server):
        client = _make_client(isolated_paths)
        _mock_config_and_cap(
            monkeypatch,
            ["inline", "bridge"],
            input_schema_fields={"backup_id": {"type": "string"}},
        )
        url = f"http://127.0.0.1:{bridge_server.server_port}/backup/bk_1"
        captured: dict = {}
        _mock_submit_and_wait(
            monkeypatch, {"status": "ok", "download_url": url, "backup_id": "bk_1"},
            captured,
        )
        _wire_client(monkeypatch, isolated_paths, client)

        out = isolated_paths / "restore.bin"
        rc = cli.main([
            "--json", "file", "get", "bk_1", "--cap", "backup.restore", "-o", str(out),
        ])
        assert rc == 0
        assert out.read_bytes() == b"payload-from-storage"
        assert captured["payload"] == {"backup_id": "bk_1"}
        result = json.loads(capsys.readouterr().out)
        assert result["mode"] == "bridge"

    def test_get_bridge_inline_fallback(self, isolated_paths, monkeypatch, capsys):
        """A bridge-capable cap that returns data_base64 (small file) is
        written inline without streaming."""
        client = _make_client(isolated_paths)
        _mock_config_and_cap(
            monkeypatch,
            ["inline", "bridge"],
            input_schema_fields={"backup_id": {"type": "string"}},
        )
        payload_bytes = b"small-backup"
        _mock_submit_and_wait(
            monkeypatch,
            {"status": "ok", "data_base64": base64.b64encode(payload_bytes).decode(),
             "backup_id": "bk_9"},
        )
        _wire_client(monkeypatch, isolated_paths, client)

        out = isolated_paths / "small.bin"
        rc = cli.main(["--json", "file", "get", "bk_9", "--cap", "backup.restore", "-o", str(out)])
        assert rc == 0
        assert out.read_bytes() == payload_bytes


# ---------------------------------------------------------------------------
# parser wiring
# ---------------------------------------------------------------------------


class TestFileParser:
    def test_file_subcommands_in_help(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            cli.main(["file", "--help"])
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        for sub in ("send", "get"):
            assert sub in out

    def test_file_subcommands_parse(self):
        parser = cli.build_parser()
        cases = [
            ["--json", "file", "send", "/tmp/f.bin", "--cap", "storage.store"],
            ["--json", "file", "send", "/tmp/f.bin", "--cap", "backup.create", "--force", "bridge"],
            ["--json", "file", "get", "some/path", "--cap", "storage.fetch", "-o", "/tmp/out"],
            ["--json", "file", "get", "bk_1", "--cap", "backup.restore"],
        ]
        for argv in cases:
            ns = parser.parse_args(argv)
            assert hasattr(ns, "func"), f"no func set for {argv}"