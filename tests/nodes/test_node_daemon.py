"""Tests for nodes.common.node_daemon (SSE-driven reference daemon).

Covers:
  * SSE parsing + event dispatch
  * ``stage_claimed`` triggers a claim for an advertised capability
  * ``task_created`` triggers a claim attempt for each claimable capability
  * reconnect on a broken SSE connection
  * stop event terminates the daemon cleanly
  * failure budget (max_retries) is honoured

The end-to-end SSE behaviour (real httpx stream against a live server) is
exercised by ``tests/test_events.py``; here we focus on the daemon's
reaction to events and its lifecycle, using stubs so no network is needed.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any

import httpx
import pytest

from nodes.common import node_config as cl
from nodes.common import node_daemon as nd
from nodes.common import node_utils
from nodes.common.node_cli import RelayClient

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
        timeout: 5
      - name: mflux
        version: "1.0.0"
        auto_publish: true
        claimable: false
""").strip()


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

    # node_daemon re-exports / imports paths from node_cli + node_utils.
    monkeypatch.setattr(nd, "BASE_DIR", base)
    monkeypatch.setattr(nd, "PID_PATH", base / "node-daemon.pid")
    monkeypatch.setattr(nd, "LOG_PATH", base / "node-daemon.log")
    monkeypatch.setattr(nd, "STATUS_PATH", base / "worker_status.json")

    monkeypatch.setattr(node_utils, "BASE_DIR", base)
    monkeypatch.setattr(node_utils, "CONFIG_PATH", base / "relay_config.json")
    monkeypatch.setattr(node_utils, "META_PATH", base / "ai-relay-agent.json")
    monkeypatch.setattr(node_utils, "TOKEN_PATH", base / "ai-relay-agent.token")
    monkeypatch.setattr(node_utils, "STATUS_PATH", base / "worker_status.json")

    profiles_dir.mkdir(parents=True, exist_ok=True)
    _write(active, VALID_PROFILE)
    _write(active_name, "default")
    return base


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content + "\n", encoding="utf-8")
    return path


def _make_daemon(
    isolated_paths: Path,
    monkeypatch: pytest.MonkeyPatch,
    cfg: dict[str, Any] | None = None,
):
    """Build an SseDaemon with a stub RelayClient (no network)."""
    _write(isolated_paths / "ai-relay-agent.token", "rt_test")
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
            self.claim = lambda name: None
            self.complete = lambda task_id, stage_id, result: {}
            self.heartbeat = lambda caps, inflight: {"status": "ok"}

    stub = _StubClient()
    daemon = nd.SseDaemon(stub, full_cfg)
    return daemon, stub


# ---------------------------------------------------------------------------
# SSE parsing
# ---------------------------------------------------------------------------

def test_parse_sse_returns_event_with_type_and_data():
    lines = ["event: task_created", 'data: {"task_id": "t1"}']
    event = nd.SseDaemon._parse_sse(lines)
    assert event is not None
    assert event["type"] == "task_created"
    assert event["data"] == {"task_id": "t1"}


def test_parse_sse_missing_data_returns_none():
    assert nd.SseDaemon._parse_sse(["event: noop"]) is None


def test_parse_sse_invalid_json_wraps_raw():
    event = nd.SseDaemon._parse_sse(["event: weird", "data: not-json"])
    assert event["type"] == "weird"
    assert event["data"] == {"raw": "not-json"}


def test_parse_sse_defaults_event_type_to_message():
    event = nd.SseDaemon._parse_sse(['data: {"x": 1}'])
    assert event["type"] == "message"


# ---------------------------------------------------------------------------
# Event dispatch
# ---------------------------------------------------------------------------

def test_stage_claimed_triggers_claim_for_advertised_capability(
    isolated_paths: Path, monkeypatch: pytest.MonkeyPatch
):
    """A stage_claimed event for a capability this node advertises causes a claim."""
    daemon, client = _make_daemon(isolated_paths, monkeypatch)

    claimed_caps: list[str] = []
    stage = {"stage_id": "s1", "task_id": "t1", "capability": "chat.ai", "payload": {}}

    def fake_claim(name):
        claimed_caps.append(name)
        return stage

    client.claim = fake_claim

    run_calls: list[tuple] = []
    monkeypatch.setattr(daemon, "_run_stage", lambda cap, st: run_calls.append((cap["name"], st)))

    daemon._on_event({"type": "stage_claimed", "data": {"capability": "chat.ai"}})

    assert claimed_caps == ["chat.ai"]
    assert run_calls == [("chat.ai", stage)]


def test_stage_claimed_ignored_for_unadvertised_capability(
    isolated_paths: Path, monkeypatch: pytest.MonkeyPatch
):
    daemon, client = _make_daemon(isolated_paths, monkeypatch)

    called = {"claim": False}
    client.claim = lambda name: called.__setitem__("claim", True) or None  # type: ignore[assignment]
    monkeypatch.setattr(daemon, "_run_stage", lambda *a, **k: None)

    daemon._on_event({"type": "stage_claimed", "data": {"capability": "does.not.exist"}})

    assert called["claim"] is False


def test_stage_claimed_without_capability_field_is_noop(
    isolated_paths: Path, monkeypatch: pytest.MonkeyPatch
):
    daemon, client = _make_daemon(isolated_paths, monkeypatch)
    client.claim = lambda name: pytest.fail("claim should not be called")
    daemon._on_event({"type": "stage_claimed", "data": {}})


def test_task_created_triggers_claim_for_each_claimable_capability(
    isolated_paths: Path, monkeypatch: pytest.MonkeyPatch
):
    """task_created attempts a claim for each claimable capability under max_parallel."""
    daemon, client = _make_daemon(isolated_paths, monkeypatch)

    claimed: list[str] = []
    stage = {"stage_id": "s1", "task_id": "t1", "capability": "chat.ai", "payload": {}}

    def fake_claim(name):
        claimed.append(name)
        return stage if name == "chat.ai" else None

    client.claim = fake_claim
    monkeypatch.setattr(daemon, "_run_stage", lambda cap, st: None)

    daemon._on_event({"type": "task_created", "data": {"task_id": "t1"}})

    # Only chat.ai is claimable (mflux has claimable: false).
    assert claimed == ["chat.ai"]


def test_task_created_skips_capability_at_max_parallel(
    isolated_paths: Path, monkeypatch: pytest.MonkeyPatch
):
    daemon, client = _make_daemon(isolated_paths, monkeypatch)

    with daemon._lock:
        daemon._in_flight["chat.ai"] = 2  # max_parallel == 2

    client.claim = lambda name: pytest.fail("should not claim when at max_parallel")
    daemon._on_event({"type": "task_created", "data": {"task_id": "t1"}})


def test_unknown_event_type_is_ignored(
    isolated_paths: Path, monkeypatch: pytest.MonkeyPatch
):
    daemon, client = _make_daemon(isolated_paths, monkeypatch)
    client.claim = lambda name: pytest.fail("should not claim")
    daemon._on_event({"type": "node_online", "data": {"node_id": "x"}})


# ---------------------------------------------------------------------------
# Claim + failure budget
# ---------------------------------------------------------------------------

def test_try_claim_and_run_skips_task_over_failure_budget(
    isolated_paths: Path, monkeypatch: pytest.MonkeyPatch
):
    daemon, client = _make_daemon(isolated_paths, monkeypatch, cfg={"max_retries": 2})
    daemon._failed_tasks["t_bad"] = 2

    client.claim = lambda name: {"stage_id": "s", "task_id": "t_bad", "capability": name, "payload": {}}
    monkeypatch.setattr(daemon, "_run_stage", lambda *a, **k: pytest.fail("must not run"))

    daemon._try_claim_and_run("chat.ai")  # should not raise


def test_try_claim_and_run_executes_within_budget(
    isolated_paths: Path, monkeypatch: pytest.MonkeyPatch
):
    daemon, client = _make_daemon(isolated_paths, monkeypatch, cfg={"max_retries": 2})
    stage = {"stage_id": "s", "task_id": "t_ok", "capability": "chat.ai", "payload": {}}
    client.claim = lambda name: stage

    run_called = {"v": False}

    def fake_run(cap, st):
        run_called["v"] = True

    monkeypatch.setattr(daemon, "_run_stage", fake_run)
    daemon._try_claim_and_run("chat.ai")
    assert run_called["v"] is True


def test_try_claim_and_run_handles_claim_exception(
    isolated_paths: Path, monkeypatch: pytest.MonkeyPatch
):
    daemon, client = _make_daemon(isolated_paths, monkeypatch)

    def boom(name):
        raise RuntimeError("network down")

    client.claim = boom
    monkeypatch.setattr(daemon, "_run_stage", lambda *a, **k: pytest.fail("must not run"))
    # Must not raise.
    daemon._try_claim_and_run("chat.ai")


def test_try_claim_and_run_no_stage_returned_is_noop(
    isolated_paths: Path, monkeypatch: pytest.MonkeyPatch
):
    daemon, client = _make_daemon(isolated_paths, monkeypatch)
    client.claim = lambda name: None
    monkeypatch.setattr(daemon, "_run_stage", lambda *a, **k: pytest.fail("must not run"))
    daemon._try_claim_and_run("chat.ai")


# ---------------------------------------------------------------------------
# Stage execution (mirrors node-cli daemon behaviour)
# ---------------------------------------------------------------------------

def test_run_stage_increments_failed_tasks_on_error_result(
    isolated_paths: Path, monkeypatch: pytest.MonkeyPatch
):
    daemon, client = _make_daemon(isolated_paths, monkeypatch)
    cap = {"name": "chat.ai", "handler": "true", "max_parallel": 1, "timeout": 5}
    stage = {"stage_id": "s1", "task_id": "t1", "capability": "chat.ai", "payload": {}}

    monkeypatch.setattr(nd, "run_handler", lambda *a, **k: {"error": "boom"})
    completed: list[dict] = []
    client.complete = lambda task_id, stage_id, result: completed.append(result)  # type: ignore

    daemon._run_stage(cap, stage)

    assert daemon._failed_tasks.get("t1") == 1
    assert daemon.tasks_failed == 1
    assert daemon._in_flight["chat.ai"] == 0
    assert completed and completed[0] == {"error": "boom"}


def test_run_stage_increments_completed_on_success(
    isolated_paths: Path, monkeypatch: pytest.MonkeyPatch
):
    daemon, client = _make_daemon(isolated_paths, monkeypatch)
    cap = {"name": "chat.ai", "handler": "true", "max_parallel": 1, "timeout": 5}
    stage = {"stage_id": "s2", "task_id": "t2", "capability": "chat.ai", "payload": {}}

    monkeypatch.setattr(nd, "run_handler", lambda *a, **k: {"answer": "ok"})
    client.complete = lambda task_id, stage_id, result: {}  # type: ignore

    daemon._run_stage(cap, stage)

    assert daemon.tasks_completed == 1
    assert daemon.tasks_failed == 0
    assert daemon._in_flight["chat.ai"] == 0


def test_run_stage_decrements_in_flight_on_handler_exception(
    isolated_paths: Path, monkeypatch: pytest.MonkeyPatch
):
    daemon, client = _make_daemon(isolated_paths, monkeypatch)
    cap = {"name": "chat.ai", "handler": "true", "max_parallel": 1, "timeout": 5}
    stage = {"stage_id": "s3", "task_id": "t3", "capability": "chat.ai", "payload": {}}

    def raise_exc(*a, **k):
        raise RuntimeError("handler crashed")

    monkeypatch.setattr(nd, "run_handler", raise_exc)
    client.complete = lambda *a, **k: {}  # type: ignore

    daemon._run_stage(cap, stage)

    assert daemon._failed_tasks.get("t3") == 1
    assert daemon._in_flight["chat.ai"] == 0


# ---------------------------------------------------------------------------
# Stream URL + consume_stream (mocked httpx)
# ---------------------------------------------------------------------------

def test_stream_url_contains_node_and_types(isolated_paths: Path, monkeypatch: pytest.MonkeyPatch):
    daemon, _ = _make_daemon(isolated_paths, monkeypatch)
    url = daemon._stream_url()
    assert "node=n1" in url
    assert "types=stage_claimed,task_created" in url
    assert url.startswith("http://relay.test/relay/v2/events/stream")


def test_consume_stream_parses_and_dispatches_events(
    isolated_paths: Path, monkeypatch: pytest.MonkeyPatch
):
    """A single SSE block is parsed and dispatched to _on_event."""
    daemon, _ = _make_daemon(isolated_paths, monkeypatch)

    # Build a fake async streaming response.
    sse_block = (
        "event: task_created\n"
        'data: {"task_id": "t_new", "task_name": "demo"}\n'
        "\n"
    )

    class _FakeResp:
        def raise_for_status(self):
            pass

        async def aiter_lines(self):
            for line in sse_block.splitlines(keepends=False):
                yield line
            yield ""  # blank line terminates the block

    class _FakeCtx:
        async def __aenter__(self):
            return _FakeResp()

        async def __aexit__(self, *a):
            return False

    class _FakeAsyncClient:
        def stream(self, *a, **k):
            return _FakeCtx()

    dispatched: list[dict] = []
    monkeypatch.setattr(daemon, "_on_event", lambda ev: dispatched.append(ev))

    import asyncio
    asyncio.run(daemon._consume_stream(_FakeAsyncClient(), "http://x", {}))  # type: ignore[arg-type]

    assert len(dispatched) == 1
    assert dispatched[0]["type"] == "task_created"
    assert dispatched[0]["data"]["task_id"] == "t_new"


def test_consume_stream_stops_on_stop_event(
    isolated_paths: Path, monkeypatch: pytest.MonkeyPatch
):
    """When _stop_event is set mid-stream, _consume_stream returns promptly."""
    daemon, _ = _make_daemon(isolated_paths, monkeypatch)

    class _FakeResp:
        def raise_for_status(self):
            pass

        async def aiter_lines(self):
            # Simulate the server holding the connection open. The stop
            # event is checked before each line; once set we return.
            for _ in range(50):
                if daemon._stop_event.is_set():
                    return
                yield "event: task_created"
                yield 'data: {"task_id": "x"}'
                yield ""

    class _FakeCtx:
        async def __aenter__(self):
            return _FakeResp()

        async def __aexit__(self, *a):
            return False

    class _FakeAsyncClient:
        def stream(self, *a, **k):
            return _FakeCtx()

    monkeypatch.setattr(daemon, "_on_event", lambda ev: daemon._stop_event.set())

    import asyncio
    asyncio.run(daemon._consume_stream(_FakeAsyncClient(), "http://x", {}))  # type: ignore[arg-type])


# ---------------------------------------------------------------------------
# Reconnect
# ---------------------------------------------------------------------------

def test_sse_loop_async_reconnects_after_error(
    isolated_paths: Path, monkeypatch: pytest.MonkeyPatch
):
    """A stream error triggers a reconnect attempt, until stop is requested."""
    daemon, _ = _make_daemon(isolated_paths, monkeypatch)

    # Speed up the reconnect delay.
    monkeypatch.setattr(nd, "_RECONNECT_DELAY", 0.01)

    attempts = {"n": 0}

    async def fake_consume(http, url, headers):
        attempts["n"] += 1
        if attempts["n"] >= 2:
            daemon._stop_event.set()
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(daemon, "_consume_stream", fake_consume)

    import asyncio
    asyncio.run(daemon._sse_loop_async())

    assert attempts["n"] >= 2


# ---------------------------------------------------------------------------
# Lifecycle: stop() terminates run()
# ---------------------------------------------------------------------------

def test_run_stops_when_stop_event_set(isolated_paths: Path, monkeypatch: pytest.MonkeyPatch):
    """run() returns once _stop_event is set (no real threads started)."""
    daemon, _ = _make_daemon(isolated_paths, monkeypatch)

    # Avoid starting real threads / signal handlers.
    monkeypatch.setattr(daemon, "_install_signal_handlers", lambda: None)
    monkeypatch.setattr(daemon, "_write_status", lambda *a, **k: None)
    monkeypatch.setattr(daemon, "_start_heartbeat_thread", lambda: None)

    started = {"sse": False}

    def fake_start_sse(*a, **k):
        started["sse"] = True

    # Replace Thread so no real thread runs; run() will just sleep-loop.
    import threading

    class _FakeThread:
        def __init__(self, *a, **k):
            self._target = k.get("target")
            self._started = False

        def start(self):
            self._started = True

        def is_alive(self):
            return self._started

        def join(self, timeout=None):
            self._started = False

    monkeypatch.setattr(threading, "Thread", _FakeThread)

    # Trigger stop shortly after run() starts.
    def fast_sleep(seconds):
        daemon._stop_event.set()

    monkeypatch.setattr(nd.time, "sleep", fast_sleep)

    daemon.run()
    assert daemon._sse_thread is not None


def test_stop_sets_stop_event(isolated_paths: Path, monkeypatch: pytest.MonkeyPatch):
    daemon, _ = _make_daemon(isolated_paths, monkeypatch)
    assert daemon._stop_event.is_set() is False
    daemon.stop()
    assert daemon._stop_event.is_set() is True


# ---------------------------------------------------------------------------
# Status file
# ---------------------------------------------------------------------------

def test_write_status_includes_daemon_marker(
    isolated_paths: Path, monkeypatch: pytest.MonkeyPatch
):
    daemon, _ = _make_daemon(isolated_paths, monkeypatch)
    daemon._failed_tasks["t_x"] = 3
    daemon._write_status()

    data = json.loads((isolated_paths / "worker_status.json").read_text())
    assert data["daemon"] == "node-daemon"
    assert data["failed_tasks"] == {"t_x": 3}
    assert data["node_id"] == "n1"


# ---------------------------------------------------------------------------
# CLI parser / entry point
# ---------------------------------------------------------------------------

def test_build_parser_has_foreground_flag():
    parser = nd.build_parser()
    args = parser.parse_args(["--foreground"])
    assert args.foreground is True


def test_build_parser_log_level_option():
    parser = nd.build_parser()
    args = parser.parse_args(["--log-level", "DEBUG"])
    assert args.log_level == "DEBUG"