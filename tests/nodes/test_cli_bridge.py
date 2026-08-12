"""Tests for the ``node-cli bridge`` subcommand (T-153).

Covers ``bridge upload`` / ``bridge download`` for both the storage
channel (``storage.upload_channel`` / ``storage.download_channel``) and
the backup path (``backup.create mode=bridge`` / ``backup.restore``).

We mock ``RelayClient.submit_simple_task`` and ``get_task`` so no network
is needed for the task lifecycle, and stand up a tiny local HTTP server to
exercise the actual chunked streaming against the returned bridge URL.
"""

from __future__ import annotations

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
# Fixtures
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
    """Patch the facade so with_client() hands our prepared client out."""
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
# Fake bridge server — captures the uploaded body / serves a download body
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
        # T-162: echo the original filename so the caller can restore it.
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
# Helpers to mock the task lifecycle
# ---------------------------------------------------------------------------


def _mock_task_lifecycle(monkeypatch, upload_url=None, download_url=None, inline=None):
    """Mock submit_simple_task + get_task so _wait_for_result returns a
    completed stage carrying the given bridge URL / inline data."""

    def fake_submit(self, capability, payload, *, name="", priority=0, owner_node_id=None):
        return {"task_id": "tsk_bridge", "status": "pending"}

    def fake_get(self, task_id):
        if download_url is not None:
            result = {"status": "restored", "download_url": download_url}
        elif upload_url is not None:
            result = {"status": "open", "upload_url": upload_url, "channel_id": "ch_x"}
        elif inline is not None:
            result = {"status": "restored", "data_base64": inline}
        else:
            result = {}
        return {
            "task": {"task_id": task_id, "status": "completed"},
            "stages": [{"status": "completed", "result": result}],
            "notes": [],
            "artifacts": [],
        }

    monkeypatch.setattr(RelayClient, "submit_simple_task", fake_submit)
    monkeypatch.setattr(RelayClient, "get_task", fake_get)


# ---------------------------------------------------------------------------
# bridge upload
# ---------------------------------------------------------------------------


class TestBridgeUpload:
    def test_upload_storage_streams_file(self, isolated_paths, monkeypatch, capsys, bridge_server):
        client = _make_client(isolated_paths)
        src = isolated_paths / "big.bin"
        src.write_bytes(b"x" * 100_000)
        url = f"http://127.0.0.1:{bridge_server.server_port}/relay/v2/dashboard/api/node-routes/n1/upload/ch_x"
        _mock_task_lifecycle(monkeypatch, upload_url=url)
        _wire_client(monkeypatch, isolated_paths, client)

        rc = cli.main(["bridge", "upload", str(src), "--channel", "ch_x"])
        assert rc == 0
        assert _BridgeHandler.uploaded == b"x" * 100_000
        assert _BridgeHandler.seen_auth == "Bearer rt_test"
        out = capsys.readouterr().out
        assert "100000" in out

    def test_upload_backup_uses_backup_create(self, isolated_paths, monkeypatch, capsys, bridge_server):
        client = _make_client(isolated_paths)
        captured = {}

        def fake_submit(self, capability, payload, *, name="", priority=0, owner_node_id=None):
            captured.update(capability=capability, payload=payload)
            return {"task_id": "tsk_bk"}

        def fake_get(self, task_id):
            return {
                "task": {"status": "completed"},
                "stages": [{"status": "completed", "result": {
                    "status": "created", "backup_id": "bk_123",
                    "upload_url": f"http://127.0.0.1:{bridge_server.server_port}/bk/123",
                }}],
                "notes": [], "artifacts": [],
            }

        monkeypatch.setattr(RelayClient, "submit_simple_task", fake_submit)
        monkeypatch.setattr(RelayClient, "get_task", fake_get)
        _wire_client(monkeypatch, isolated_paths, client)

        src = isolated_paths / "save.tar.gz"
        src.write_bytes(b"backupdata")
        rc = cli.main(["bridge", "upload", str(src), "--backup", "--source", "sims4", "--type", "full"])
        assert rc == 0
        assert captured["capability"] == "backup.create"
        assert captured["payload"]["mode"] == "bridge"
        assert captured["payload"]["source"] == "sims4"
        assert captured["payload"]["type"] == "full"
        # T-162: the original filename is carried so a restore keeps it.
        assert captured["payload"]["filename"] == "save.tar.gz"
        assert _BridgeHandler.uploaded == b"backupdata"
        out = capsys.readouterr().out
        assert "bk_123" in out

    def test_upload_missing_file(self, isolated_paths, monkeypatch, capsys):
        client = _make_client(isolated_paths)
        _wire_client(monkeypatch, isolated_paths, client)
        rc = cli.main(["bridge", "upload", str(isolated_paths / "nope.bin")])
        assert rc == 2
        err = capsys.readouterr().err
        assert "file not found" in err.lower()


# ---------------------------------------------------------------------------
# bridge download
# ---------------------------------------------------------------------------


class TestBridgeDownload:
    def test_download_storage_streams_to_file(self, isolated_paths, monkeypatch, capsys, bridge_server):
        client = _make_client(isolated_paths)
        url = f"http://127.0.0.1:{bridge_server.server_port}/relay/v2/dashboard/api/node-routes/n1/download/ch_y"
        _mock_task_lifecycle(monkeypatch, download_url=url)
        _wire_client(monkeypatch, isolated_paths, client)

        out_path = isolated_paths / "out.bin"
        rc = cli.main(["bridge", "download", "--channel", "ch_y", "-o", str(out_path)])
        assert rc == 0
        assert out_path.read_bytes() == b"payload-from-storage"
        assert _BridgeHandler.seen_auth == "Bearer rt_test"

    def test_download_backup_restores_inline(self, isolated_paths, monkeypatch, capsys):
        client = _make_client(isolated_paths)
        import base64
        payload = b"small-backup"
        _mock_task_lifecycle(monkeypatch, inline=base64.b64encode(payload).decode())
        _wire_client(monkeypatch, isolated_paths, client)

        out_path = isolated_paths / "restore.bin"
        rc = cli.main(["bridge", "download", "--backup", "bk_999", "-o", str(out_path)])
        assert rc == 0
        assert out_path.read_bytes() == payload

    def test_download_backup_streams_large(self, isolated_paths, monkeypatch, capsys, bridge_server):
        client = _make_client(isolated_paths)
        url = f"http://127.0.0.1:{bridge_server.server_port}/backup/888"
        _mock_task_lifecycle(monkeypatch, download_url=url)
        _wire_client(monkeypatch, isolated_paths, client)

        out_path = isolated_paths / "large.bin"
        rc = cli.main(["bridge", "download", "--backup", "bk_888", "-o", str(out_path)])
        assert rc == 0
        assert out_path.read_bytes() == b"payload-from-storage"

    def test_download_defaults_to_x_filename_header(self, isolated_paths, monkeypatch, capsys, bridge_server, tmp_path):
        """T-162: without -o, the caller restores the original filename
        from the X-Filename response header instead of the channel id.
        The file lands in the current working directory."""
        client = _make_client(isolated_paths)
        url = f"http://127.0.0.1:{bridge_server.server_port}/download/ch_y"
        _mock_task_lifecycle(monkeypatch, download_url=url)
        _wire_client(monkeypatch, isolated_paths, client)
        _BridgeHandler.download_filename = "sims4-save.tar.gz"

        monkeypatch.chdir(tmp_path)
        rc = cli.main(["bridge", "download", "--channel", "ch_y"])
        assert rc == 0
        out = tmp_path / "sims4-save.tar.gz"
        assert out.read_bytes() == b"payload-from-storage"

    def test_download_requires_channel_or_backup(self, isolated_paths, monkeypatch, capsys):
        client = _make_client(isolated_paths)
        _wire_client(monkeypatch, isolated_paths, client)
        rc = cli.main(["bridge", "download", "-o", "x.bin"])
        assert rc == 2
        err = capsys.readouterr().err
        assert "--channel" in err or "--backup" in err


# ---------------------------------------------------------------------------
# parser wiring
# ---------------------------------------------------------------------------


class TestBridgeParser:
    def test_bridge_subcommands_in_help(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            cli.main(["bridge", "--help"])
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        for sub in ("upload", "download"):
            assert sub in out

    def test_bridge_subcommands_parse(self):
        parser = cli.build_parser()
        cases = [
            ["bridge", "upload", "/tmp/f.bin", "--backup", "--source", "s", "--type", "full"],
            ["bridge", "upload", "/tmp/f.bin", "--channel", "ch_x"],
            ["bridge", "download", "--channel", "ch_x", "-o", "/tmp/out"],
            ["bridge", "download", "--backup", "bk_1", "-o", "/tmp/out"],
        ]
        for argv in cases:
            ns = parser.parse_args(argv)
            assert hasattr(ns, "func"), f"no func set for {argv}"
