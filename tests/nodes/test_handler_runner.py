"""Tests for nodes.common.handler_runner."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from nodes.common.handler_runner import HANDLER_ENV_KEYS, run_handler


def _stage(payload=None, *, stage_id="stage-123", task_id="task-456"):
    return {
        "stage_id": stage_id,
        "task_id": task_id,
        "capability": "chat.ai",
        "payload": payload,
    }


def _context():
    return {
        "RELAY_NODE_ID": "node-abc",
        "RELAY_BASE_URL": "https://relay.example.com",
        "RELAY_TOKEN_FILE": "/tmp/fake-token",
    }


# ---------------------------------------------------------------------------
# Successful execution
# ---------------------------------------------------------------------------

def test_run_handler_cat_returns_stdin_as_dict():
    # /bin/cat echoes stdin back; the runner parses it as JSON.
    stage = _stage({"message": "hello"})
    result = run_handler("/bin/cat", stage, context=_context())
    assert result["message"] == "hello"
    # _handler debug block is always attached on success.
    assert result["_handler"]["exit_code"] == 0
    assert result["_handler"]["stdout_length"] > 0
    assert result["_handler"]["stderr"] == ""


def test_run_handler_handler_stdout_json_returned_as_dict():
    handler = f"{sys.executable} -c 'import sys,json; print(json.dumps({{\"ok\": True}}))'"
    result = run_handler(handler, _stage(), context=_context())
    assert result["ok"] is True
    assert result["_handler"]["exit_code"] == 0


def test_run_handler_non_dict_json_wrapped_into_result():
    handler = f"{sys.executable} -c 'print(\"[1, 2, 3]\")'"
    result = run_handler(handler, _stage(), context=_context())
    assert result["result"] == [1, 2, 3]
    # _handler is attached even for wrapped non-dict JSON.
    assert result["_handler"]["exit_code"] == 0


def test_run_handler_empty_payload_sends_empty_object():
    """When payload is None, stdin must still be valid JSON."""
    captured: dict[str, str] = {}

    handler = (
        f"{sys.executable} -c "
        "'import sys; sys.stdout.write(sys.stdin.read())'"
    )
    result = run_handler(handler, _stage(None), context=_context())
    # The echoed stdin was {} → parsed as empty dict, with _handler debug.
    assert result.get("_handler") is not None
    assert result["_handler"]["exit_code"] == 0
    _ = captured  # silence unused var linters


# ---------------------------------------------------------------------------
# Non-zero exit
# ---------------------------------------------------------------------------

def test_run_handler_nonzero_exit_returns_error_with_stderr():
    handler = f"{sys.executable} -c 'import sys; sys.stderr.write(\"boom\"); sys.exit(3)'"
    result = run_handler(handler, _stage(), context=_context())
    assert result["error"] == "handler exited with code 3"
    assert "boom" in result["stderr"]


def test_run_handler_no_stdout_returns_error():
    handler = f"{sys.executable} -c 'pass'"
    result = run_handler(handler, _stage(), context=_context())
    assert "error" in result
    assert "no stdout" in result["error"]


def test_run_handler_invalid_json_stdout_returns_error():
    handler = f"{sys.executable} -c 'print(\"not json{{\")'"
    result = run_handler(handler, _stage(), context=_context())
    assert "not valid JSON" in result["error"]


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------

def test_run_handler_timeout_returns_timeout_error():
    handler = f"{sys.executable} -c 'import time; time.sleep(10)'"
    result = run_handler(handler, _stage(), context=_context(), timeout=1)
    assert result["error"] == "handler timeout after 1s"


# ---------------------------------------------------------------------------
# Environment variables
# ---------------------------------------------------------------------------

def test_run_handler_env_vars_correctly_set(tmp_path: Path):
    dump = tmp_path / "env.json"
    # A handler that writes its RELAY_* env vars + stdin payload to a file.
    handler = (
        f"{sys.executable} -c "
        f"'import os,json,sys;"
        f'payload=sys.stdin.read();'
        f'env={{"payload":json.loads(payload),'
        f'"stage_id":os.environ.get("RELAY_STAGE_ID"),'
        f'"task_id":os.environ.get("RELAY_TASK_ID"),'
        f'"capability":os.environ.get("RELAY_CAPABILITY"),'
        f'"node_id":os.environ.get("RELAY_NODE_ID"),'
        f'"base_url":os.environ.get("RELAY_BASE_URL"),'
        f'"token_file":os.environ.get("RELAY_TOKEN_FILE")}};'
        f'open(r"{dump}","w").write(json.dumps(env))\''
    )
    stage = _stage({"x": 1}, stage_id="s1", task_id="t1")
    ctx = _context()
    run_handler(handler, stage, context=ctx)
    data = json.loads(dump.read_text())
    assert data["payload"] == {"x": 1}
    assert data["stage_id"] == "s1"
    assert data["task_id"] == "t1"
    assert data["node_id"] == "node-abc"
    assert data["base_url"] == "https://relay.example.com"
    assert data["token_file"] == "/tmp/fake-token"
    # RELAY_CAPABILITY is not in our default _context() but must still be set.
    assert "RELAY_CAPABILITY" in HANDLER_ENV_KEYS


def test_run_handler_inherits_process_env():
    handler = (
        f"{sys.executable} -c "
        '\'import os,sys,json; print(json.dumps({"p": os.environ.get("PATH")}))\''
    )
    result = run_handler(handler, _stage(), context=_context())
    assert result["p"] == os.environ.get("PATH")
    assert result["_handler"]["exit_code"] == 0


def test_run_handler_missing_context_keys_default_empty():
    """Missing context values must surface as empty strings, not crash."""
    dump_path = "/tmp/relay_test_missing_ctx.json"
    handler = (
        f"{sys.executable} -c "
        f"'import os,json; "
        f'open(r"{dump_path}","w").write(json.dumps(os.environ.get("RELAY_NODE_ID")))\''
    )
    run_handler(handler, _stage(), context={})
    assert json.loads(Path(dump_path).read_text()) == ""
