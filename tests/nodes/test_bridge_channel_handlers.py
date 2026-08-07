"""Tests for the bridge channel handlers (T-129).

``upload_channel`` / ``download_channel`` run as claimable tasks: they
register a temp bridge route on the relay and complete the task with
the public URL. We import the handler modules in-process and mock
``httpx.post`` + stdin so no real relay is contacted and no subprocess
is spawned.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

HANDLERS = Path(__file__).resolve().parents[2] / "docker" / "storage" / "handlers"

# Add the handlers dir to sys.path so ``import _common`` / the handler
# modules resolve. The handlers live under docker/storage/handlers which
# is not a package; add it once for the whole module.
sys.path.insert(0, str(HANDLERS))

import download_channel  # noqa: E402
import upload_channel  # noqa: E402


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = json.dumps(self._payload)

    def json(self) -> dict:
        return self._payload


def _run_handler_in_process(mod, payload: dict, tmp_path: Path, monkeypatch):
    """Run a handler module's main() in-process with mocked env + stdin."""
    token = tmp_path / "token.json"
    token.write_text(json.dumps({"token": "rt_fake", "expires_at": None}))
    monkeypatch.setenv("RELAY_NODE_ID", "node-abc")
    monkeypatch.setenv("RELAY_BASE_URL", "http://relay.test")
    monkeypatch.setenv("RELAY_TOKEN_FILE", str(token))
    monkeypatch.setenv("NODE_ENDPOINT", "http://storage-node:8791")
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    captured: dict = {}

    def _capture_stdout(s: str) -> None:
        captured["stdout"] = s

    # The handlers call _emit / _fail which sys.exit. We capture stdout
    # and swallow the SystemExit.
    import _common

    def emit(result):
        captured["result"] = result
        _common.sys.stdout.write(json.dumps(result))
        raise SystemExit(0)

    def fail(msg):
        captured["error"] = msg
        _common.sys.stdout.write(json.dumps({"error": msg}))
        raise SystemExit(1)

    monkeypatch.setattr(_common, "_emit", emit)
    monkeypatch.setattr(_common, "_fail", fail)
    monkeypatch.setattr(mod, "_emit", emit, raising=False)
    monkeypatch.setattr(mod, "_fail", fail, raising=False)

    with pytest.raises(SystemExit):
        mod.main()
    return captured


# ---------------------------------------------------------------------------
# upload_channel
# ---------------------------------------------------------------------------


class TestUploadChannel:
    def test_registers_route_and_returns_upload_url(self, tmp_path: Path, monkeypatch):
        captured: dict = {}

        def fake_post(url, *, headers, json, timeout):  # noqa: ARG001
            captured.update(url=url, headers=headers, body=json)
            return _FakeResponse(
                200,
                {
                    "status": "ok",
                    "node_id": "node-abc",
                    "path": "/upload/ch_x",
                    "method": "POST",
                    "expires_at": "2026-08-07T20:00:00+00:00",
                    "channel_id": "ch_x",
                },
            )

        with patch.object(httpx, "post", side_effect=fake_post):
            out = _run_handler_in_process(
                upload_channel, {"channel_id": "ch_x"}, tmp_path, monkeypatch
            )

        assert out["result"]["status"] == "open"
        assert out["result"]["channel_id"] == "ch_x"
        assert out["result"]["upload_url"] == (
            "http://relay.test/relay/v2/dashboard/api/node-routes/node-abc/upload/ch_x"
        )
        assert out["result"]["expires_at"] == "2026-08-07T20:00:00+00:00"
        assert out["result"]["ttl"] == 3600
        assert captured["url"] == "http://relay.test/relay/v2/dashboard/api/node-routes/register"
        assert captured["headers"]["Authorization"] == "Bearer rt_fake"
        assert captured["body"]["path"] == "/upload/ch_x"
        assert captured["body"]["method"] == "POST"
        assert captured["body"]["upstream"] == "http://storage-node:8791/upload/ch_x"
        assert captured["body"]["channel_id"] == "ch_x"
        assert captured["body"]["ttl_seconds"] == 3600

    def test_mints_channel_id_when_absent(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("RELAY_TASK_ID", "tk_99")

        def fake_post(url, **kw):  # noqa: ARG001
            body = kw.get("json", {})
            return _FakeResponse(
                200,
                {
                    "status": "ok",
                    "node_id": "node-abc",
                    "path": body["path"],
                    "method": "POST",
                    "expires_at": "2026-08-07T20:00:00+00:00",
                    "channel_id": body["channel_id"],
                },
            )

        with patch.object(httpx, "post", side_effect=fake_post):
            out = _run_handler_in_process(upload_channel, {}, tmp_path, monkeypatch)

        assert out["result"]["status"] == "open"
        assert out["result"]["channel_id"] == "ch_tk_99"
        assert "ch_tk_99" in out["result"]["upload_url"]

    def test_register_failure_fails_stage(self, tmp_path: Path, monkeypatch):
        def fake_post(url, **kw):  # noqa: ARG001
            return _FakeResponse(400, {"detail": "bad path"})

        with patch.object(httpx, "post", side_effect=fake_post):
            out = _run_handler_in_process(
                upload_channel, {"channel_id": "ch_bad"}, tmp_path, monkeypatch
            )
        assert "error" in out
        assert "register failed" in out["error"]

    def test_missing_env_fails(self, tmp_path: Path, monkeypatch):
        token = tmp_path / "token.json"
        token.write_text(json.dumps({"token": "rt_fake", "expires_at": None}))
        monkeypatch.setenv("RELAY_NODE_ID", "node-abc")
        monkeypatch.setenv("RELAY_BASE_URL", "")  # missing
        monkeypatch.setenv("RELAY_TOKEN_FILE", str(token))
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"channel_id": "ch_x"})))
        out: dict = {}

        def fail(msg):
            out["error"] = msg
            raise SystemExit(1)

        import _common

        monkeypatch.setattr(_common, "_fail", fail, raising=False)
        monkeypatch.setattr(upload_channel, "_fail", fail, raising=False)
        with pytest.raises(SystemExit):
            upload_channel.main()
        assert "RELAY_BASE_URL" in out["error"]


# ---------------------------------------------------------------------------
# download_channel
# ---------------------------------------------------------------------------


class TestDownloadChannel:
    def test_registers_route_and_returns_download_url(self, tmp_path: Path, monkeypatch):
        captured: dict = {}

        def fake_post(url, *, headers, json, timeout):  # noqa: ARG001
            captured.update(url=url, headers=headers, body=json)
            return _FakeResponse(
                200,
                {
                    "status": "ok",
                    "node_id": "node-abc",
                    "path": "/download/ch_dl",
                    "method": "GET",
                    "expires_at": "2026-08-07T21:00:00+00:00",
                    "channel_id": "ch_dl",
                },
            )

        with patch.object(httpx, "post", side_effect=fake_post):
            out = _run_handler_in_process(
                download_channel, {"channel_id": "ch_dl"}, tmp_path, monkeypatch
            )

        assert out["result"]["status"] == "open"
        assert out["result"]["channel_id"] == "ch_dl"
        assert out["result"]["download_url"] == (
            "http://relay.test/relay/v2/dashboard/api/node-routes/node-abc/download/ch_dl"
        )
        assert captured["body"]["method"] == "GET"
        assert captured["body"]["upstream"] == "http://storage-node:8791/download/ch_dl"

    def test_missing_channel_id_fails(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({})))
        out: dict = {}

        def fail(msg):
            out["error"] = msg
            raise SystemExit(1)

        import _common

        monkeypatch.setattr(_common, "_fail", fail, raising=False)
        monkeypatch.setattr(download_channel, "_fail", fail, raising=False)
        with pytest.raises(SystemExit):
            download_channel.main()
        assert "channel_id" in out["error"]
