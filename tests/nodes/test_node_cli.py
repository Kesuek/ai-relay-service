"""Tests for nodes.common.node_cli (CLI skeleton + capabilities + parse checks)."""

from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

import httpx
import pytest

from nodes.common import capability_loader as cl
from nodes.common import node_cli as cli
from nodes.common import node_utils

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_PROFILE = textwrap.dedent("""
    capabilities:
      - name: chat.ai
        version: "1.0.0"
        auto_publish: true
        claimable: true
        handler: /opt/relay/handlers/chat-ai.sh
        max_parallel: 2
        timeout: 300
      - name: mflux
        version: "1.0.0"
        auto_publish: true
        claimable: false
""").strip()

BAD_PROFILE = "capabilities: not-a-list\n"


@pytest.fixture()
def isolated_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    base = tmp_path / "relay"
    profiles_dir = base / "capabilities.d"
    active = base / "capabilities.active.yaml"
    active_name = base / "capabilities.active.profile"

    # capability_loader module globals.
    monkeypatch.setattr(cl, "BASE_DIR", base)
    monkeypatch.setattr(cl, "PROFILES_DIR", profiles_dir)
    monkeypatch.setattr(cl, "ACTIVE_PATH", active)
    monkeypatch.setattr(cl, "ACTIVE_PROFILE_NAME_PATH", active_name)
    monkeypatch.setattr(cl._active_cache, "path", active)

    # node_cli module globals (re-exported from capability_loader/poller).
    monkeypatch.setattr(cli, "BASE_DIR", base)
    monkeypatch.setattr(cli, "PROFILES_DIR", profiles_dir)
    monkeypatch.setattr(cli, "ACTIVE_PATH", active)
    # PID / LOG / STATUS paths used by the daemon control commands.
    monkeypatch.setattr(cli, "PID_PATH", base / "node-cli.pid")
    monkeypatch.setattr(cli, "LOG_PATH", base / "node-cli.log")
    monkeypatch.setattr(cli, "STATUS_PATH", base / "worker_status.json")

    # node_utils module globals used by RelayClient.
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


# ---------------------------------------------------------------------------
# argparse / help
# ---------------------------------------------------------------------------

EXPECTED_SUBCOMMANDS = {
    "daemon",
    "heartbeat",
    "claim",
    "complete",
    "task",
    "capabilities",
    "status",
    "reload",
    "artifact",
    "docs",
    "update",
}


def test_help_shows_all_subcommands(capsys: pytest.CaptureFixture[str]):
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--help"])
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    for cmd in EXPECTED_SUBCOMMANDS:
        assert cmd in out, f"subcommand {cmd!r} missing from --help"


def test_all_subcommands_parse_without_errors():
    """Every documented subcommand must parse its arguments without error."""
    parser = cli.build_parser()
    cases = [
        ["daemon", "start"],
        ["daemon", "stop"],
        ["daemon", "status"],
        ["daemon", "restart"],
        ["daemon", "foreground"],
        ["heartbeat"],
        ["claim", "chat.ai"],
        ["complete", "stage-1", "--task", "task-1", "--result-file", "/tmp/r.json"],
        ["task", "submit", "--name", "n", "--stage", "chat.ai:{\"x\":1}", "--priority", "2"],
        ["task", "submit", "--name", "n", "--stage", "chat.ai:{\"x\":1}", "--owner", "node_a"],
        ["task", "result", "tsk_abc"],
        ["task", "wait", "tsk_abc"],
        ["task", "wait", "tsk_abc", "--interval", "3"],
        ["task", "note", "tsk_abc", "starting fetch"],
        ["capabilities", "list"],
        ["capabilities", "validate", "default"],
        ["capabilities", "validate"],
        ["capabilities", "publish", "default"],
        ["capabilities", "diff", "default"],
        ["capabilities", "diff"],
        ["capabilities", "current"],
        ["capabilities", "server"],
        ["capabilities", "info", "chat.ai"],
        ["status"],
        ["reload"],
        ["artifact", "download", "artifact_123"],
        ["artifact", "download", "artifact_123", "--output", "/tmp/out.bin"],
        ["artifact", "download", "artifact_123", "-o", "/tmp/out.bin"],
        ["docs"],
        ["docs", "node-setup"],
        ["update", "check"],
        ["update", "apply"],
        ["update", "apply", "--service-unit", "custom.service"],
    ]
    for argv in cases:
        ns = parser.parse_args(argv)
        assert hasattr(ns, "func"), f"no func set for {argv}"


def test_unknown_command_exits_nonzero():
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["does-not-exist"])
    assert exc_info.value.code != 0


# ---------------------------------------------------------------------------
# capabilities list
# ---------------------------------------------------------------------------

def test_capabilities_list_shows_profiles(isolated_paths: Path, capsys: pytest.CaptureFixture[str]):
    _write(isolated_paths / "capabilities.d" / "alpha.yaml", VALID_PROFILE)
    _write(isolated_paths / "capabilities.d" / "beta.yaml", VALID_PROFILE)
    rc = cli.main(["capabilities", "list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "alpha" in out
    assert "beta" in out


def test_capabilities_list_empty(isolated_paths: Path, capsys: pytest.CaptureFixture[str]):
    rc = cli.main(["capabilities", "list"])
    assert rc == 0
    assert "no profiles" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# capabilities validate
# ---------------------------------------------------------------------------

def test_capabilities_validate_detects_bad_profile(
    isolated_paths: Path, capsys: pytest.CaptureFixture[str]
):
    _write(isolated_paths / "capabilities.d" / "bad.yaml", BAD_PROFILE)
    rc = cli.main(["capabilities", "validate", "bad"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "INVALID" in err


def test_capabilities_validate_ok_for_valid_profile(
    isolated_paths: Path, capsys: pytest.CaptureFixture[str]
):
    _write(isolated_paths / "capabilities.d" / "default.yaml", VALID_PROFILE)
    rc = cli.main(["capabilities", "validate", "default"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "OK" in out
    assert "chat.ai" in out


def test_capabilities_validate_active_by_default(
    isolated_paths: Path, capsys: pytest.CaptureFixture[str]
):
    # No active file and no profile name → error.
    rc = cli.main(["capabilities", "validate"])
    assert rc == 1


# ---------------------------------------------------------------------------
# capabilities publish
# ---------------------------------------------------------------------------

def test_capabilities_publish_creates_active_file(isolated_paths: Path):
    _write(isolated_paths / "capabilities.d" / "default.yaml", VALID_PROFILE)
    rc = cli.main(["capabilities", "publish", "default"])
    assert rc == 0
    active = isolated_paths / "capabilities.active.yaml"
    assert active.exists()
    # Active file content == source profile content.
    src = isolated_paths / "capabilities.d" / "default.yaml"
    assert active.read_text() == src.read_text()
    # Name file recorded.
    name_file = isolated_paths / "capabilities.active.profile"
    assert name_file.read_text().strip() == "default"


def test_capabilities_publish_invalid_returns_nonzero(isolated_paths: Path):
    _write(isolated_paths / "capabilities.d" / "bad.yaml", BAD_PROFILE)
    rc = cli.main(["capabilities", "publish", "bad"])
    assert rc != 0
    assert not (isolated_paths / "capabilities.active.yaml").exists()


def test_capabilities_current_after_publish(
    isolated_paths: Path, capsys: pytest.CaptureFixture[str]
):
    _write(isolated_paths / "capabilities.d" / "default.yaml", VALID_PROFILE)
    assert cli.main(["capabilities", "publish", "default"]) == 0
    capsys.readouterr()  # discard publish output
    rc = cli.main(["capabilities", "current"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "default"


def test_capabilities_current_unset_returns_nonzero(isolated_paths: Path):
    rc = cli.main(["capabilities", "current"])
    assert rc != 0


# ---------------------------------------------------------------------------
# capabilities diff
# ---------------------------------------------------------------------------

def test_capabilities_diff_shows_changes(isolated_paths: Path, capsys: pytest.CaptureFixture[str]):
    _write(isolated_paths / "capabilities.d" / "default.yaml", VALID_PROFILE)
    cli.main(["capabilities", "publish", "default"])
    # Now modify the working profile: bump chat.ai version, add a new cap.
    modified = textwrap.dedent("""
        capabilities:
          - name: chat.ai
            version: "2.0.0"
            auto_publish: true
            claimable: true
            handler: /opt/relay/handlers/chat-ai.sh
            max_parallel: 2
            timeout: 300
          - name: mflux
            version: "1.0.0"
            auto_publish: true
            claimable: false
          - name: new.cap
            version: "1.0.0"
            auto_publish: true
            claimable: false
    """).strip()
    _write(isolated_paths / "capabilities.d" / "default.yaml", modified)
    rc = cli.main(["capabilities", "diff", "default"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "+ new.cap" in out
    assert "~ chat.ai" in out
    assert "2.0.0" in out


def test_capabilities_diff_no_changes(isolated_paths: Path, capsys: pytest.CaptureFixture[str]):
    _write(isolated_paths / "capabilities.d" / "default.yaml", VALID_PROFILE)
    cli.main(["capabilities", "publish", "default"])
    rc = cli.main(["capabilities", "diff", "default"])
    assert rc == 0
    assert "no differences" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# status / reload (no daemon running)
# ---------------------------------------------------------------------------

def test_status_no_status_file_returns_nonzero(isolated_paths: Path):
    rc = cli.main(["status"])
    assert rc != 0


def test_status_shows_json_when_file_present(
    isolated_paths: Path, capsys: pytest.CaptureFixture[str]
):
    status = {"pid": 123, "node_id": "n1", "heartbeat_status": "ok"}
    _write(isolated_paths / "worker_status.json", json.dumps(status))
    rc = cli.main(["status"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "ok" in out
    assert "123" in out


def test_reload_no_daemon_returns_nonzero(isolated_paths: Path):
    rc = cli.main(["reload"])
    assert rc != 0


def test_daemon_status_when_not_running(isolated_paths: Path, capsys: pytest.CaptureFixture[str]):
    rc = cli.main(["daemon", "status"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "running: False" in out


# ---------------------------------------------------------------------------
# task submit argument parsing
# ---------------------------------------------------------------------------

def test_task_submit_stage_parse_ok():
    cap, payload = cli._parse_stage_arg('chat.ai:{"x":1}')
    assert cap == "chat.ai"
    assert payload == {"x": 1}


def test_task_submit_stage_empty_payload_ok():
    cap, payload = cli._parse_stage_arg("chat.ai:")
    assert cap == "chat.ai"
    assert payload == {}


def test_task_submit_stage_invalid_no_colon():
    with pytest.raises(SystemExit):
        cli._parse_stage_arg("chat-ai")


def test_task_submit_stage_invalid_json():
    with pytest.raises(SystemExit):
        cli._parse_stage_arg("chat.ai:not-json")


def test_task_submit_with_owner(isolated_paths: Path, monkeypatch):
    """--owner flag is forwarded as owner_node_id in the request body."""
    base = isolated_paths
    _write(base / "relay_config.json", json.dumps({"base_url": "http://relay:8788", "request_timeout": 10}))
    _write(base / "ai-relay-agent.json", json.dumps({"node_id": "n1", "registration_secret": "rs_abc"}))
    _write(base / "ai-relay-agent.token", "rt_test")

    captured: dict = {}

    def fake_post(url, **kw):
        captured["url"] = url
        captured["body"] = kw.get("json")
        class FakeResp:
            status_code = 200
            def json(self):
                return {"task_id": "task_x", "status": "pending", "stage_count": 1}
            def raise_for_status(self):
                pass
        return FakeResp()

    monkeypatch.setattr(httpx, "post", fake_post)

    client = cli.RelayClient(
        json.loads((base / "ai-relay-agent.json").read_text()),
        json.loads((base / "relay_config.json").read_text()),
    )
    result = client.submit_simple_task(
        "chat.ai",
        {"x": 1},
        name="pinned",
        priority=3,
        owner_node_id="node_target",
    )

    assert result["task_id"] == "task_x"
    assert "/relay/v2/scheduler/task-simple" in captured["url"]
    body = captured["body"]
    assert body["owner_node_id"] == "node_target"
    assert body["capability"] == "chat.ai"
    assert body["priority"] == 3
    assert body["name"] == "pinned"


def test_task_submit_without_owner_omits_field(isolated_paths: Path, monkeypatch):
    """When --owner is not given, owner_node_id must not be sent in the body."""
    base = isolated_paths
    _write(base / "relay_config.json", json.dumps({"base_url": "http://relay:8788", "request_timeout": 10}))
    _write(base / "ai-relay-agent.json", json.dumps({"node_id": "n1", "registration_secret": "rs_abc"}))
    _write(base / "ai-relay-agent.token", "rt_test")

    captured: dict = {}

    def fake_post(url, **kw):
        captured["body"] = kw.get("json")
        class FakeResp:
            status_code = 200
            def json(self):
                return {"task_id": "t1", "status": "pending", "stage_count": 1}
            def raise_for_status(self):
                pass
        return FakeResp()

    monkeypatch.setattr(httpx, "post", fake_post)

    client = cli.RelayClient(
        json.loads((base / "ai-relay-agent.json").read_text()),
        json.loads((base / "relay_config.json").read_text()),
    )
    client.submit_simple_task("chat.ai", {"x": 1})
    assert "owner_node_id" not in captured["body"]


# ---------------------------------------------------------------------------
# artifact download
# ---------------------------------------------------------------------------


class _FakeStreamResponse:
    """Minimal stand-in for an httpx streaming Response."""

    def __init__(self, *, status_code: int, chunks, headers: dict | None = None) -> None:
        self.status_code = status_code
        self._chunks = list(chunks)
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error", request=None, response=self  # type: ignore[arg-type]
            )

    def iter_bytes(self, chunk_size: int = 65536):  # noqa: ARG002
        for c in self._chunks:
            yield c


class _FakeStreamCM:
    """Context manager returned by a mocked ``httpx.stream``."""

    def __init__(self, response: _FakeStreamResponse) -> None:
        self._response = response
        self.entered = False

    def __enter__(self) -> _FakeStreamResponse:
        self.entered = True
        return self._response

    def __exit__(self, *exc) -> None:
        return None


def _write_token(base: Path) -> Path:
    token_path = base / "ai-relay-agent.token"
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text("rt_testtoken123\n", encoding="utf-8")
    return token_path


def _make_client(base: Path, monkeypatch: pytest.MonkeyPatch):
    _write_token(base)
    meta = {"node_id": "n1", "base_url": "http://relay.test", "capabilities": []}
    cfg = {"base_url": "http://relay.test", "request_timeout": 5}
    return cli.RelayClient(meta, cfg)


def test_download_artifact_writes_streamed_content(isolated_paths: Path, monkeypatch):
    client = _make_client(isolated_paths, monkeypatch)
    payload = b"HELLO-ARTIFACT-BYTES"
    fake = _FakeStreamResponse(
        status_code=200,
        chunks=[payload[:5], payload[5:]],
        headers={"content-disposition": 'attachment; filename="report.bin"'},
    )
    cm = _FakeStreamCM(fake)
    monkeypatch.setattr(cli.httpx, "stream", lambda *a, **k: cm)

    out = isolated_paths / "downloads"
    out.mkdir(parents=True, exist_ok=True)
    target = client.download_artifact("artifact_abc", output_path=out / "report.bin")
    assert target == out / "report.bin"
    assert target.read_bytes() == payload
    assert cm.entered is True


def test_download_artifact_uses_content_disposition_filename(isolated_paths: Path, monkeypatch):
    client = _make_client(isolated_paths, monkeypatch)
    payload = b"streamed-data"
    fake = _FakeStreamResponse(
        status_code=200,
        chunks=[payload],
        headers={"content-disposition": 'inline; filename="from-server.txt"'},
    )
    monkeypatch.setattr(cli.httpx, "stream", lambda *a, **k: _FakeStreamCM(fake))
    monkeypatch.chdir(isolated_paths)

    target = client.download_artifact("artifact_xyz")
    assert target.name == "from-server.txt"
    assert target.parent == Path(".")
    assert target.read_bytes() == payload
    target.unlink(missing_ok=True)


def test_download_artifact_raises_on_http_error(isolated_paths: Path, monkeypatch):
    client = _make_client(isolated_paths, monkeypatch)
    fake = _FakeStreamResponse(status_code=404, chunks=[], headers={})
    monkeypatch.setattr(cli.httpx, "stream", lambda *a, **k: _FakeStreamCM(fake))

    with pytest.raises(httpx.HTTPStatusError):
        client.download_artifact("artifact_missing")


# artifact upload


def test_upload_artifact_sends_file(isolated_paths: Path, monkeypatch):
    """upload_artifact POSTs the file and returns the server response."""
    base = isolated_paths
    _write(base / "relay_config.json", json.dumps({"base_url": "http://relay:8788", "request_timeout": 10}))
    _write(base / "ai-relay-agent.json", json.dumps({"node_id": "n1", "registration_secret": "rs_abc"}))
    _write(base / "ai-relay-agent.token", "rt_test")

    source = base / "data.txt"
    source.write_text("hello from worker")

    responses: list[dict] = []

    def fake_post(url, **kw):
        responses.append({"url": url, "kw": kw})
        class FakeResp:
            status_code = 200
            def json(self):
                return {"artifact_id": "artifact_uploaded", "name": "data.txt", "size_bytes": 17}
            def raise_for_status(self):
                pass
        return FakeResp()

    monkeypatch.setattr(httpx, "post", fake_post)

    client = cli.RelayClient(
        json.loads((base / "ai-relay-agent.json").read_text()),
        json.loads((base / "relay_config.json").read_text()),
    )
    result = client.upload_artifact(source)

    assert result["artifact_id"] == "artifact_uploaded"
    assert len(responses) == 1
    assert "/relay/v2/storage/upload" in responses[0]["url"]
    # Verify the file was attached as multipart
    files = responses[0]["kw"].get("files", {})
    assert "file" in files


def test_upload_artifact_retries_on_401(isolated_paths: Path, monkeypatch):
    """upload_artifact retries once after a 401."""
    base = isolated_paths
    _write(base / "relay_config.json", json.dumps({"base_url": "http://relay:8788", "request_timeout": 10}))
    _write(base / "ai-relay-agent.json", json.dumps({"node_id": "n1", "registration_secret": "rs_abc"}))
    _write(base / "ai-relay-agent.token", "rt_test")

    source = base / "data.txt"
    source.write_text("data")

    call_count = 0

    def fake_post(url, **kw):
        nonlocal call_count
        call_count += 1
        class FakeResp:
            status_code = 200 if call_count > 1 else 401
            def json(self):
                return {"artifact_id": "artifact_retried", "name": "data.txt", "size_bytes": 4}
            def raise_for_status(self):
                if self.status_code >= 400:
                    raise httpx.HTTPStatusError("auth", request=None, response=self)
        return FakeResp()

    monkeypatch.setattr(httpx, "post", fake_post)
    # Mock refresh to succeed
    monkeypatch.setattr(cli.RelayClient, "_refresh_token", lambda self: True)

    client = cli.RelayClient(
        json.loads((base / "ai-relay-agent.json").read_text()),
        json.loads((base / "relay_config.json").read_text()),
    )
    result = client.upload_artifact(source)
    assert result["artifact_id"] == "artifact_retried"
    assert call_count == 2


def test_upload_artifact_passes_task_and_stage_params(isolated_paths: Path, monkeypatch):
    """upload_artifact forwards task_id and stage_id as query params."""
    base = isolated_paths
    _write(base / "relay_config.json", json.dumps({"base_url": "http://relay:8788", "request_timeout": 10}))
    _write(base / "ai-relay-agent.json", json.dumps({"node_id": "n1", "registration_secret": "rs_abc"}))
    _write(base / "ai-relay-agent.token", "rt_test")

    source = base / "data.txt"
    source.write_text("data")
    captured: dict = {}

    def fake_post(url, **kw):
        captured["url"] = url
        captured["params"] = kw.get("params")
        class FakeResp:
            status_code = 200
            def json(self):
                return {"artifact_id": "a1"}
            def raise_for_status(self):
                pass
        return FakeResp()

    monkeypatch.setattr(httpx, "post", fake_post)

    client = cli.RelayClient(
        json.loads((base / "ai-relay-agent.json").read_text()),
        json.loads((base / "relay_config.json").read_text()),
    )
    client.upload_artifact(source, task_id="task_99", stage_id="stage_88")
    assert "task_id=task_99" in captured["url"] or captured["params"] == {"task_id": "task_99", "stage_id": "stage_88"}


def test_cmd_artifact_download_invokes_client(isolated_paths: Path, monkeypatch, capsys):
    client = _make_client(isolated_paths, monkeypatch)
    payload = b"cli-payload"

    captured = {}

    def fake_download(artifact_id, output_path=None, **kw):
        captured["artifact_id"] = artifact_id
        captured["output_path"] = output_path
        target = output_path or (isolated_paths / "out.bin")
        target.write_bytes(payload)
        return target

    monkeypatch.setattr(cli.RelayClient, "download_artifact", staticmethod(fake_download))

    monkeypatch.setattr(cli, "load_meta", lambda: {"node_id": "n1", "base_url": "http://relay.test"})
    monkeypatch.setattr(cli, "_effective_config", lambda: {"base_url": "http://relay.test", "request_timeout": 5})
    monkeypatch.setattr(cli, "RelayClient", lambda meta, cfg: client)

    rc = cli.main(["artifact", "download", "artifact_cli1", "-o", str(isolated_paths / "x.bin")])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Downloaded" in out
    assert str(len(payload)) in out
    assert captured["artifact_id"] == "artifact_cli1"


def test_cmd_artifact_upload_invokes_client(isolated_paths: Path, monkeypatch, capsys):
    """node-cli artifact upload calls RelayClient.upload_artifact()."""
    base = isolated_paths
    _write(base / "relay_config.json", json.dumps({"base_url": "http://relay:8788", "request_timeout": 10}))
    _write(base / "ai-relay-agent.json", json.dumps({"node_id": "n1", "registration_secret": "rs_abc"}))
    _write(base / "ai-relay-agent.token", "rt_test")

    source = base / "upload-me.txt"
    source.write_text("payload")

    captured: dict = {}

    def fake_upload(file_path, *, name=None, task_id=None, stage_id=None, capability=None):
        captured["file_path"] = str(file_path)
        captured["name"] = name
        captured["task_id"] = task_id
        captured["stage_id"] = stage_id
        captured["capability"] = capability
        if capability:
            return {"status": "ok", "path": f"capability-pages/{capability}/dashboard.html"}
        return {"artifact_id": "a_cli", "name": name or Path(file_path).name, "size_bytes": 7}

    monkeypatch.setattr(cli.RelayClient, "upload_artifact", staticmethod(fake_upload))

    rc = cli.main(["artifact", "upload", str(source), "--name", "cli-upload.bin"])
    assert rc == 0
    assert captured["file_path"] == str(source)
    assert captured["name"] == "cli-upload.bin"
    assert captured["capability"] is None

    out = capsys.readouterr().out
    assert "a_cli" in out


def test_cmd_artifact_upload_missing_file(isolated_paths: Path, monkeypatch, capsys):
    """node-cli artifact upload exits with code 2 when file is missing."""
    base = isolated_paths
    _write(base / "relay_config.json", json.dumps({"base_url": "http://relay:8788", "request_timeout": 10}))
    _write(base / "ai-relay-agent.json", json.dumps({"node_id": "n1", "registration_secret": "rs_abc"}))
    _write(base / "ai-relay-agent.token", "rt_test")

    rc = cli.main(["artifact", "upload", "/nonexistent/file.bin"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "not found" in err


def test_poller_download_artifact_streams_to_disk(isolated_paths: Path, monkeypatch):
    _write_token(isolated_paths)
    _write(isolated_paths / "ai-relay-agent.json", json.dumps({
        "node_id": "n1",
        "base_url": "http://relay.test",
        "capabilities": [],
    }))
    client = _make_client(isolated_paths, monkeypatch)
    payload = b"poller-bytes"

    fake = _FakeStreamResponse(
        status_code=200,
        chunks=[payload[:3], payload[3:]],
        headers={"content-disposition": 'attachment; filename="poll.bin"'},
    )
    monkeypatch.setattr(cli.httpx, "stream", lambda *a, **k: _FakeStreamCM(fake))

    target = client.download_artifact("artifact_p1")
    assert target.name == "poll.bin"
    assert target.read_bytes() == payload
    target.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# task note (T-052)
# ---------------------------------------------------------------------------


def test_add_task_note_posts_to_notes_endpoint(isolated_paths: Path, monkeypatch):
    """RelayClient.add_task_note POSTs to /scheduler/tasks/{id}/notes."""
    base = isolated_paths
    _write(base / "relay_config.json", json.dumps({"base_url": "http://relay:8788", "request_timeout": 10}))
    _write(base / "ai-relay-agent.json", json.dumps({"node_id": "n1", "registration_secret": "rs_abc"}))
    _write(base / "ai-relay-agent.token", "rt_test")

    captured: dict = {}

    def fake_post(url, **kw):
        captured["url"] = url
        captured["body"] = kw.get("json")
        class FakeResp:
            status_code = 200
            def json(self):
                return {
                    "id": 42,
                    "task_id": "tsk_abc",
                    "node_id": "n1",
                    "message": captured["body"]["message"],
                    "created_at": "2026-07-20T10:00:00+00:00",
                }
            def raise_for_status(self):
                pass
        return FakeResp()

    monkeypatch.setattr(httpx, "post", fake_post)

    client = cli.RelayClient(
        json.loads((base / "ai-relay-agent.json").read_text()),
        json.loads((base / "relay_config.json").read_text()),
    )
    result = client.add_task_note("tsk_abc", "starting fetch")
    assert result["id"] == 42
    assert "/relay/v2/scheduler/tasks/tsk_abc/notes" in captured["url"]
    assert captured["body"] == {"message": "starting fetch"}


def test_cmd_task_note_invokes_client(isolated_paths: Path, monkeypatch, capsys):
    """`node-cli task note <id> <msg>` calls RelayClient.add_task_note."""
    base = isolated_paths
    _write(base / "relay_config.json", json.dumps({"base_url": "http://relay:8788", "request_timeout": 10}))
    _write(base / "ai-relay-agent.json", json.dumps({"node_id": "n1", "registration_secret": "rs_abc"}))
    _write(base / "ai-relay-agent.token", "rt_test")

    captured: dict = {}

    def fake_add_note(self, task_id, message):
        captured["task_id"] = task_id
        captured["message"] = message
        return {
            "id": 7,
            "task_id": task_id,
            "node_id": "n1",
            "message": message,
            "created_at": "2026-07-20T10:23:11+00:00",
        }

    monkeypatch.setattr(cli.RelayClient, "add_task_note", fake_add_note)
    monkeypatch.setattr(cli, "load_meta", lambda: {"node_id": "n1", "base_url": "http://relay.test"})
    monkeypatch.setattr(cli, "_effective_config", lambda: {"base_url": "http://relay.test", "request_timeout": 5})

    rc = cli.main(["task", "note", "tsk_abc", "starting fetch"])
    assert rc == 0
    assert captured["task_id"] == "tsk_abc"
    assert captured["message"] == "starting fetch"
    out = capsys.readouterr().out
    assert "Note added to task tsk_abc" in out
    assert "starting fetch" in out


def test_cmd_task_note_404_returns_nonzero(isolated_paths: Path, monkeypatch, capsys):
    """`node-cli task note` returns 1 when the server responds 404."""
    import httpx as _httpx

    base = isolated_paths
    _write(base / "relay_config.json", json.dumps({"base_url": "http://relay:8788", "request_timeout": 10}))
    _write(base / "ai-relay-agent.json", json.dumps({"node_id": "n1", "registration_secret": "rs_abc"}))
    _write(base / "ai-relay-agent.token", "rt_test")

    class FakeResp:
        status_code = 404
        text = "Task not found"
        def raise_for_status(self):
            raise _httpx.HTTPStatusError("not found", request=None, response=self)

    monkeypatch.setattr(
        cli.RelayClient,
        "add_task_note",
        lambda self, tid, msg: (_ for _ in ()).throw(_httpx.HTTPStatusError("404", request=None, response=FakeResp())),
    )
    monkeypatch.setattr(cli, "load_meta", lambda: {"node_id": "n1", "base_url": "http://relay.test"})
    monkeypatch.setattr(cli, "_effective_config", lambda: {"base_url": "http://relay.test", "request_timeout": 5})

    rc = cli.main(["task", "note", "tsk_missing", "hello"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "not found" in err.lower()


# ---------------------------------------------------------------------------
# T-053: heartbeat forwards capability metadata (description/type/input_schema)
# ---------------------------------------------------------------------------


def test_heartbeat_forwards_capability_metadata(isolated_paths: Path, monkeypatch):
    """RelayClient.heartbeat includes description/type/input_schema when present."""
    base = isolated_paths
    _write(base / "relay_config.json", json.dumps({"base_url": "http://relay:8788", "request_timeout": 10}))
    _write(base / "ai-relay-agent.json", json.dumps({"node_id": "n1", "registration_secret": "rs_abc"}))
    _write(base / "ai-relay-agent.token", "rt_test")

    caps = [
        {
            "name": "chat.ai",
            "version": "1.0.0",
            "type": "ai",
            "description": "General conversational AI.",
            "input_schema": {"fields": {"prompt": {"type": "string"}}},
            "auto_publish": True,
            "claimable": True,
            "max_parallel": 1,
        },
        {
            "name": "bare.cap",
            "version": "1.0.0",
            "auto_publish": True,
            "max_parallel": 1,
        },
    ]

    captured: dict = {}

    def fake_post(url, **kw):
        captured["body"] = kw.get("json")
        class FakeResp:
            status_code = 200
            def json(self):
                return {"status": "ok", "node_id": "n1"}
            def raise_for_status(self):
                pass
        return FakeResp()

    monkeypatch.setattr(httpx, "post", fake_post)

    client = cli.RelayClient(
        json.loads((base / "ai-relay-agent.json").read_text()),
        json.loads((base / "relay_config.json").read_text()),
    )
    client.heartbeat(caps, {})

    cap_status = captured["body"]["capabilities"]
    by_name = {c["name"]: c for c in cap_status}

    # chat.ai must carry the metadata fields.
    chat = by_name["chat.ai"]
    assert chat["type"] == "ai"
    assert chat["description"] == "General conversational AI."
    assert chat["input_schema"] == {"fields": {"prompt": {"type": "string"}}}

    # bare.cap has no metadata — those fields must be absent, not null.
    bare = by_name["bare.cap"]
    assert "type" not in bare
    assert "description" not in bare
    assert "input_schema" not in bare


# ---------------------------------------------------------------------------
# T-055: capabilities server (always shows description/schema) + info <name>
# ---------------------------------------------------------------------------


def _client_stub(isolated_paths: Path, monkeypatch: pytest.MonkeyPatch):
    """Build a RelayClient stub with valid token + meta/config on disk."""
    base = isolated_paths
    _write(base / "relay_config.json", json.dumps({"base_url": "http://relay:8788", "request_timeout": 10}))
    _write(base / "ai-relay-agent.json", json.dumps({"node_id": "n1", "registration_secret": "rs_abc"}))
    _write(base / "ai-relay-agent.token", "rt_test")
    return base


def test_capabilities_server_always_shows_description_and_schema(
    isolated_paths: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """`capabilities server` prints description + input_schema without --verbose."""
    _client_stub(isolated_paths, monkeypatch)

    payload = {
        "capabilities": [
            {
                "name": "chat.ai",
                "version": "1.0.0",
                "available": True,
                "description": "General conversational AI.",
                "input_schema": {"fields": {"prompt": {"type": "string"}}},
                "nodes": [{"node_id": "n1", "node_name": "node-1"}],
            },
            {
                "name": "bare.cap",
                "version": "2.0.0",
                "available": False,
                "nodes": [],
            },
        ]
    }

    class FakeResp:
        status_code = 200
        def json(self):
            return payload
        def raise_for_status(self):
            pass

    monkeypatch.setattr(cli.httpx, "get", lambda url, **kw: FakeResp())
    monkeypatch.setattr(cli, "load_meta", lambda: {"node_id": "n1", "base_url": "http://relay.test"})
    monkeypatch.setattr(cli, "_effective_config", lambda: {"base_url": "http://relay.test", "request_timeout": 5})

    rc = cli.main(["capabilities", "server"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "chat.ai" in out
    assert "General conversational AI." in out
    assert "Input:" in out
    assert '"fields"' in out
    # bare.cap has no description/schema — only the summary line is printed.
    assert "bare.cap" in out


def test_capabilities_server_has_no_verbose_flag():
    """The --verbose flag from T-054 was removed in T-055."""
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["capabilities", "server", "--verbose"])


def test_capabilities_info_prints_details(
    isolated_paths: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """`capabilities info <name>` queries the detail endpoint and prints fields."""
    _client_stub(isolated_paths, monkeypatch)

    payload = {
        "name": "chat.ai",
        "type": "ai",
        "description": "General conversational AI.",
        "version": "1.0.0",
        "available": True,
        "input_schema": {"fields": {"prompt": {"type": "string"}}},
        "nodes": [
            {"node_id": "n1", "node_name": "node-1", "load": 12.3, "queue_depth": 2},
        ],
    }

    captured: dict = {}

    class FakeResp:
        status_code = 200
        def json(self):
            return payload
        def raise_for_status(self):
            pass

    def fake_get(url, **kw):
        captured["url"] = url
        return FakeResp()

    monkeypatch.setattr(cli.httpx, "get", fake_get)
    monkeypatch.setattr(cli, "load_meta", lambda: {"node_id": "n1", "base_url": "http://relay.test"})
    monkeypatch.setattr(cli, "_effective_config", lambda: {"base_url": "http://relay.test", "request_timeout": 5})

    rc = cli.main(["capabilities", "info", "chat.ai"])
    assert rc == 0
    assert captured["url"].endswith("/relay/v2/discovery/capabilities/chat.ai")
    out = capsys.readouterr().out
    assert "Name:        chat.ai" in out
    assert "Type:        ai" in out
    assert "Version:     1.0.0" in out
    assert "Available:   yes" in out
    assert "Description: General conversational AI." in out
    assert "Input Schema:" in out
    assert "Nodes (1):" in out
    assert "node-1" in out
    assert "load=12.3" in out
    assert "queue=2" in out


def test_capabilities_info_404_returns_nonzero(
    isolated_paths: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """`capabilities info <name>` returns 1 when the capability is not found."""
    _client_stub(isolated_paths, monkeypatch)

    class FakeResp:
        status_code = 404
        def json(self):
            return {"detail": "not found"}
        def raise_for_status(self):
            pass

    monkeypatch.setattr(cli.httpx, "get", lambda url, **kw: FakeResp())
    monkeypatch.setattr(cli, "load_meta", lambda: {"node_id": "n1", "base_url": "http://relay.test"})
    monkeypatch.setattr(cli, "_effective_config", lambda: {"base_url": "http://relay.test", "request_timeout": 5})

    rc = cli.main(["capabilities", "info", "does.not.exist"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "not found" in out.lower()
    assert "does.not.exist" in out


# ---------------------------------------------------------------------------
# T-059: node-cli docs
# ---------------------------------------------------------------------------

# Minimal stand-in for an httpx.Response used by the docs subcommand tests.
class _FakeDocsResp:
    def __init__(self, *, status_code: int, text_body: str = "", json_data=None,
                 headers: dict | None = None) -> None:
        self.status_code = status_code
        self._text = text_body
        self._json = json_data
        self.headers = headers or {}
        if "content-type" not in self.headers and json_data is not None:
            self.headers["content-type"] = "application/json"
        if "content-type" not in self.headers and text_body:
            self.headers["content-type"] = "text/html; charset=utf-8"

    @property
    def text(self) -> str:
        return self._text

    def json(self):
        if self._json is None:
            raise ValueError("no JSON body")
        return self._json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"{self.status_code}", request=None, response=self  # type: ignore[arg-type]
            )


def _docs_client_stub(isolated_paths: Path, monkeypatch: pytest.MonkeyPatch, responses: dict):
    """Patch httpx.get so the docs subcommand gets canned responses by URL suffix.

    ``responses`` maps a trailing path (e.g. "/relay/v2/docs") to a
    _FakeDocsResp. The meta/config/RelayClient are stubbed to avoid disk I/O.
    """
    _write(isolated_paths / "relay_config.json",
           json.dumps({"base_url": "http://relay:8788", "request_timeout": 10}))
    _write(isolated_paths / "ai-relay-agent.json",
           json.dumps({"node_id": "n1", "registration_secret": "rs_abc"}))
    _write(isolated_paths / "ai-relay-agent.token", "rt_test")

    def fake_get(url, **kw):
        for suffix, resp in responses.items():
            if url.endswith(suffix):
                return resp
        # Default: 404
        return _FakeDocsResp(status_code=404, text_body="not found",
                             headers={"content-type": "text/plain"})

    monkeypatch.setattr(cli.httpx, "get", fake_get)
    monkeypatch.setattr(cli, "load_meta",
                        lambda: {"node_id": "n1", "base_url": "http://relay.test"})
    monkeypatch.setattr(cli, "_effective_config",
                        lambda: {"base_url": "http://relay.test", "request_timeout": 5})


def test_docs_list_shows_all_documents(
    isolated_paths: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """`node-cli docs` lists all available documents with name and URL."""
    payload = {
        "docs": [
            {"name": "readme", "url": "/relay/v2/docs/readme", "available": True,
             "title": "README"},
            {"name": "node-setup", "url": "/relay/v2/docs/node-setup", "available": True,
             "title": "setup"},
            {"name": "missing-doc", "url": "/relay/v2/docs/missing-doc", "available": False,
             "title": "missing"},
        ]
    }
    _docs_client_stub(isolated_paths, monkeypatch, {
        "/relay/v2/docs": _FakeDocsResp(status_code=200, json_data=payload),
    })

    rc = cli.main(["docs"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Relay documentation (3 pages)" in out
    assert "readme" in out
    assert "/relay/v2/docs/readme" in out
    assert "node-setup" in out
    assert "/relay/v2/docs/node-setup" in out
    # Unavailable docs are still listed but marked differently.
    assert "missing-doc" in out


def test_docs_single_renders_html_as_text(
    isolated_paths: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """`node-cli docs <name>` fetches the HTML page and prints readable text."""
    html = """<!DOCTYPE html>
<html><head><title>setup — AI Relay Docs</title>
<style>body { color: red; }</style></head>
<body>
<h1>Node Setup</h1>
<p>Install the runtime token at <code>~/.relay/ai-relay-agent.token</code>.</p>
<ul><li>Step one</li><li>Step two</li></ul>
</body></html>"""
    _docs_client_stub(isolated_paths, monkeypatch, {
        "/relay/v2/docs/node-setup": _FakeDocsResp(
            status_code=200, text_body=html,
            headers={"content-type": "text/html; charset=utf-8"},
        ),
    })

    rc = cli.main(["docs", "node-setup"])
    assert rc == 0
    out = capsys.readouterr().out
    # Tag content is gone, text content survives.
    assert "<html" not in out
    assert "<style" not in out
    assert "Node Setup" in out
    assert "Install the runtime token" in out
    assert "ai-relay-agent.token" in out
    assert "Step one" in out
    assert "Step two" in out


def test_docs_single_accepts_json_with_content(
    isolated_paths: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """If the server returns JSON with a `content`/`markdown` field, print it."""
    payload = {"name": "concepts", "content": "# Concepts\n\nNodes are capability-driven."}
    _docs_client_stub(isolated_paths, monkeypatch, {
        "/relay/v2/docs/concepts": _FakeDocsResp(
            status_code=200, json_data=payload,
            headers={"content-type": "application/json"},
        ),
    })

    rc = cli.main(["docs", "concepts"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "capability-driven" in out


def test_docs_not_found_returns_nonzero(
    isolated_paths: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """`node-cli docs nonexistent` exits 1 and reports the missing document."""
    _docs_client_stub(isolated_paths, monkeypatch, {
        "/relay/v2/docs/unknown-doc": _FakeDocsResp(
            status_code=404, text_body="Document not found",
            headers={"content-type": "text/plain"},
        ),
    })

    rc = cli.main(["docs", "unknown-doc"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "unknown-doc" in err
    assert "not found" in err.lower()


def test_docs_list_handles_bare_list_payload(
    isolated_paths: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """The list endpoint sometimes returns a bare list instead of {docs: [...]}."""
    payload = [
        {"name": "readme", "url": "/relay/v2/docs/readme"},
        {"name": "changelog", "url": "/relay/v2/docs/changelog"},
    ]
    _docs_client_stub(isolated_paths, monkeypatch, {
        "/relay/v2/docs": _FakeDocsResp(status_code=200, json_data=payload),
    })

    rc = cli.main(["docs"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Relay documentation (2 pages)" in out
    assert "readme" in out
    assert "changelog" in out


# ---------------------------------------------------------------------------
# T-060: daemon _failed_tasks tracking + claim loop skip
# ---------------------------------------------------------------------------


def _make_daemon(isolated_paths: Path, cfg: dict | None = None):
    """Build a Daemon with a stub RelayClient (no real network/token I/O)."""
    base = isolated_paths
    _write(base / "ai-relay-agent.token", "rt_test")
    meta = {"node_id": "n1", "base_url": "http://relay.test"}
    full_cfg = {
        "base_url": "http://relay.test",
        "request_timeout": 5,
        "heartbeat_interval": 999,
        "claim_interval": 999,
        "max_retries": 2,
    }
    if cfg:
        full_cfg.update(cfg)

    class _StubClient:
        def __init__(self):
            self.meta = meta
            self.base_url = meta["base_url"]
            self.token = "rt_test"
            # Placeholder callables so monkeypatch.setattr can replace them.
            self.claim = lambda name: None
            self.complete = lambda task_id, stage_id, result: {}

    stub = _StubClient()
    return cli.Daemon(stub, full_cfg), stub


def test_daemon_failed_tasks_default_empty(isolated_paths: Path):
    """Daemon starts with an empty _failed_tasks dict."""
    daemon, _ = _make_daemon(isolated_paths)
    assert daemon._failed_tasks == {}


def test_daemon_run_stage_increments_failed_tasks_on_error_result(
    isolated_paths: Path, monkeypatch: pytest.MonkeyPatch
):
    """A handler result with an 'error' key bumps the per-task failure counter."""
    daemon, client = _make_daemon(isolated_paths)

    cap = {"name": "chat.ai", "handler": "true", "max_parallel": 1, "timeout": 5}
    stage = {"stage_id": "s1", "task_id": "t1", "capability": "chat.ai", "payload": {}}

    # Force run_handler to return an error result, and complete() to succeed
    # so the failure-counting path under the complete() branch is exercised.
    monkeypatch.setattr(cli, "run_handler", lambda *a, **k: {"error": "boom"})
    completed: list[dict] = []

    def fake_complete(task_id, stage_id, result):
        completed.append({"task_id": task_id, "stage_id": stage_id, "result": result})

    daemon.client.complete = fake_complete  # type: ignore[attr-defined]

    daemon._run_stage(cap, stage)

    assert daemon._failed_tasks.get("t1") == 1
    assert daemon.tasks_failed == 1
    assert completed and completed[0]["result"] == {"error": "boom"}


def test_daemon_run_stage_increments_failed_tasks_on_handler_exception(
    isolated_paths: Path, monkeypatch: pytest.MonkeyPatch
):
    """A handler exception bumps the per-task failure counter."""
    daemon, client = _make_daemon(isolated_paths)

    cap = {"name": "chat.ai", "handler": "true", "max_parallel": 1, "timeout": 5}
    stage = {"stage_id": "s2", "task_id": "t2", "capability": "chat.ai", "payload": {}}

    def raise_exc(*a, **k):
        raise RuntimeError("handler crashed")

    monkeypatch.setattr(cli, "run_handler", raise_exc)
    daemon._run_stage(cap, stage)

    assert daemon._failed_tasks.get("t2") == 1
    assert daemon.tasks_failed == 1


def test_daemon_claim_loop_skips_task_after_max_retries(
    isolated_paths: Path, monkeypatch: pytest.MonkeyPatch
):
    """A claimed stage for a task with failures >= max_retries is skipped (not run)."""
    daemon, client = _make_daemon(isolated_paths, cfg={"claim_interval": 999, "max_retries": 2})

    # Pre-seed the failure counter so the task is already over budget.
    daemon._failed_tasks["t_bad"] = 2

    claimed_stage = {"stage_id": "s_bad", "task_id": "t_bad", "capability": "chat.ai", "payload": {}}
    cap = {"name": "chat.ai", "handler": "true", "claimable": True, "max_parallel": 1, "timeout": 5}

    monkeypatch.setattr(cli, "load_active_profile", lambda: [cap])
    monkeypatch.setattr(daemon.client, "claim", lambda name: claimed_stage)

    # run_stage must NOT be called — patch it to fail the test if it is.
    def fail_if_called(*a, **k):
        raise AssertionError("run_stage should not be called for a skipped task")

    monkeypatch.setattr(daemon, "_run_stage", fail_if_called)

    # Stop the loop after one iteration so the test terminates.
    iterations = {"n": 0}

    def stop_after_one(*a, **k):
        iterations["n"] += 1
        if iterations["n"] >= 1:
            daemon._stop_event.set()
        return 0

    monkeypatch.setattr(cli.time, "sleep", stop_after_one)

    daemon._claim_loop()
    # If we got here without AssertionError, the skip path worked.


def test_daemon_claim_loop_runs_stage_within_budget(
    isolated_paths: Path, monkeypatch: pytest.MonkeyPatch
):
    """A claimed stage for a task below the failure budget is run normally."""
    daemon, client = _make_daemon(isolated_paths, cfg={"claim_interval": 999, "max_retries": 2})

    claimed_stage = {"stage_id": "s_ok", "task_id": "t_ok", "capability": "chat.ai", "payload": {}}
    cap = {"name": "chat.ai", "handler": "true", "claimable": True, "max_parallel": 1, "timeout": 5}

    monkeypatch.setattr(cli, "load_active_profile", lambda: [cap])
    monkeypatch.setattr(daemon.client, "claim", lambda name: claimed_stage)

    run_called = {"v": False}

    def fake_run_stage(c, s):
        run_called["v"] = True
        daemon._stop_event.set()

    monkeypatch.setattr(daemon, "_run_stage", fake_run_stage)
    monkeypatch.setattr(cli.time, "sleep", lambda *a, **k: None)

    daemon._claim_loop()
    assert run_called["v"] is True


def test_daemon_status_file_includes_failed_tasks(isolated_paths: Path, monkeypatch: pytest.MonkeyPatch):
    """_write_status surfaces failed_tasks so `node-cli daemon status` can show it."""
    daemon, _ = _make_daemon(isolated_paths)
    daemon._failed_tasks["t_x"] = 3

    daemon._write_status()

    import json as _json
    data = _json.loads((isolated_paths / "worker_status.json").read_text())
    assert data["failed_tasks"] == {"t_x": 3}


# ---------------------------------------------------------------------------
# T-062: update check / update apply
# ---------------------------------------------------------------------------

from nodes.common import node_utils  # noqa: E402 — alias for clarity below


def _make_repo(tmp_path: Path) -> Path:
    """Create a real throwaway git repo with one commit and an origin remote."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), check=True)
    (repo / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=str(repo), check=True)
    return repo


def _add_commit(repo: Path, msg: str = "change") -> str:
    """Add another commit to ``repo`` and return its SHA."""
    (repo / "README.md").write_text(f"{msg}\n")
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=str(repo), check=True)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repo), capture_output=True, text=True, check=True
    ).stdout.strip()


def test_update_check_no_updates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys):
    """When local == upstream, `update check` reports 'up to date' and rc=0."""
    repo = _make_repo(tmp_path)
    # Configure a bogus upstream pointing at the repo itself so rev-list HEAD..@{u} == 0
    subprocess.run(["git", "remote", "add", "origin", str(repo)], cwd=str(repo), check=True)
    subprocess.run(["git", "fetch", "-q", "origin"], cwd=str(repo), check=True)
    subprocess.run(
        ["git", "branch", "--set-upstream-to=origin/main", "main"], cwd=str(repo), check=True
    )

    monkeypatch.setattr(node_utils, "REPO_DIR", repo)
    monkeypatch.setattr(cli, "REPO_DIR", repo)

    rc = cli.main(["update", "check"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "up to date" in out
    assert "Upstream:       yes" in out


def test_update_check_with_updates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys):
    """When local is behind upstream, `update check` reports the count and rc=0."""
    repo = _make_repo(tmp_path)
    # Create a separate "origin" repo that has an extra commit, then point
    # the working repo at it so the working clone is behind by 1.
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "-b", "main", "--bare", str(origin)], cwd=str(tmp_path), check=True)
    # Push the initial commit to origin.
    subprocess.run(["git", "remote", "add", "origin", str(origin)], cwd=str(repo), check=True)
    subprocess.run(["git", "push", "-q", "origin", "main"], cwd=str(repo), check=True)
    subprocess.run(
        ["git", "branch", "--set-upstream-to=origin/main", "main"], cwd=str(repo), check=True
    )
    # Now add a commit directly to the bare origin (clone, commit, push back).
    work = tmp_path / "work"
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(work), check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(work), check=True)
    _add_commit(work, "new-on-origin")
    subprocess.run(["git", "push", "-q", "origin", "main"], cwd=str(work), check=True)

    monkeypatch.setattr(node_utils, "REPO_DIR", repo)
    monkeypatch.setattr(cli, "REPO_DIR", repo)

    rc = cli.main(["update", "check"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "behind" in out
    assert "update available" in out


def test_update_apply(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys):
    """`update apply` pulls and restarts the service, reporting success."""
    repo = _make_repo(tmp_path)
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "-b", "main", "--bare", str(origin)], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "remote", "add", "origin", str(origin)], cwd=str(repo), check=True)
    subprocess.run(["git", "push", "-q", "origin", "main"], cwd=str(repo), check=True)
    subprocess.run(
        ["git", "branch", "--set-upstream-to=origin/main", "main"], cwd=str(repo), check=True
    )
    before = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repo), capture_output=True, text=True, check=True
    ).stdout.strip()

    # Add a new commit on origin via a working clone, then push.
    work = tmp_path / "work"
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(work), check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(work), check=True)
    new_sha = _add_commit(work, "new-on-origin")
    subprocess.run(["git", "push", "-q", "origin", "main"], cwd=str(work), check=True)

    monkeypatch.setattr(node_utils, "REPO_DIR", repo)
    monkeypatch.setattr(cli, "REPO_DIR", repo)

    # Stub systemctl so no real service is touched, but let real git through.
    real_run = node_utils.subprocess.run

    def fake_run(cmd, **kw):
        if "systemctl" in cmd:
            class R:
                returncode = 0
                stdout = ""
                stderr = ""
            return R()
        return real_run(cmd, **kw)

    monkeypatch.setattr(node_utils.subprocess, "run", fake_run)

    rc = cli.main(["update", "apply", "--service-unit", "test.service"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Restarted: yes" in out
    assert new_sha in out
    assert before in out


def test_update_apply_no_upstream(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys):
    """Without a configured upstream, `update apply` still runs git pull (which
    may succeed or fail) — here we just assert the command does not crash and
    reports a result. We stub git pull via a fake subprocess to simulate the
    no-upstream case cleanly."""
    repo = _make_repo(tmp_path)
    monkeypatch.setattr(node_utils, "REPO_DIR", repo)
    monkeypatch.setattr(cli, "REPO_DIR", repo)

    # Stub subprocess.run so git pull fails (no upstream) but systemctl is fine.
    calls = {"pull": False, "restart": False}

    class _R:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, **kw):
        if "pull" in cmd:
            calls["pull"] = True
            raise subprocess.CalledProcessError(returncode=1, cmd=cmd, output="", stderr="no upstream")
        if "restart" in cmd:
            calls["restart"] = True
            return _R()
        return _R()

    monkeypatch.setattr(node_utils.subprocess, "run", fake_run)

    rc = cli.main(["update", "apply"])
    assert rc == 1  # pull failed -> success=False -> rc=1
    out = capsys.readouterr().out
    assert "git pull failed" in out
    # Restart must not be attempted when pull failed.
    assert calls["restart"] is False


def test_get_repo_info_no_git_repo(tmp_path: Path):
    """get_repo_info returns a zeroed dict when the dir is not a git repo."""
    info = node_utils.get_repo_info(repo_dir=tmp_path / "does-not-exist")
    assert info["local_commit"] is None
    assert info["has_upstream"] is False
    assert info["behind_count"] == 0
