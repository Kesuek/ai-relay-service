"""Tests for nodes.common.node_cli (CLI skeleton + capabilities + parse checks)."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import httpx
import pytest

from nodes.common import capability_loader as cl
from nodes.common import node_cli as cli
from nodes.common import poller

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

    # poller module globals used by RelayClient.
    monkeypatch.setattr(poller, "BASE_DIR", base)
    monkeypatch.setattr(poller, "CONFIG_PATH", base / "relay_config.json")
    monkeypatch.setattr(poller, "META_PATH", base / "ai-relay-agent.json")
    monkeypatch.setattr(poller, "TOKEN_PATH", base / "ai-relay-agent.token")
    monkeypatch.setattr(poller, "STATUS_PATH", base / "worker_status.json")

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
        ["capabilities", "list"],
        ["capabilities", "validate", "default"],
        ["capabilities", "validate"],
        ["capabilities", "publish", "default"],
        ["capabilities", "diff", "default"],
        ["capabilities", "diff"],
        ["capabilities", "current"],
        ["status"],
        ["reload"],
        ["artifact", "download", "artifact_123"],
        ["artifact", "download", "artifact_123", "--output", "/tmp/out.bin"],
        ["artifact", "download", "artifact_123", "-o", "/tmp/out.bin"],
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


def test_poller_download_artifact_streams_to_disk(isolated_paths: Path, monkeypatch):
    _write_token(isolated_paths)
    _write(isolated_paths / "ai-relay-agent.json", json.dumps({
        "node_id": "n1",
        "base_url": "http://relay.test",
        "capabilities": [],
    }))
    poller_obj = poller.Poller()
    payload = b"poller-bytes"

    fake = _FakeStreamResponse(
        status_code=200,
        chunks=[payload[:3], payload[3:]],
        headers={"content-disposition": 'attachment; filename="poll.bin"'},
    )
    monkeypatch.setattr(poller.httpx, "stream", lambda *a, **k: _FakeStreamCM(fake))

    target = poller_obj.download_artifact("artifact_p1")
    assert target.name == "poll.bin"
    assert target.read_bytes() == payload
    target.unlink(missing_ok=True)
