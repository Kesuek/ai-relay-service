# Node CLI — Generic Daemon with External Capabilities (Push Model)

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Build a generic `node-cli` tool that decouples worker scripts from direct Relay HTTP calls. The CLI runs as a background daemon (heartbeat + claim loop). Capabilities are defined in external YAML profile files and explicitly published to the daemon.

**Architecture:** A single Python CLI entry point (`node-cli`) uses the existing `nodes/common/poller.py` library for auth, heartbeat, claim, and complete. Capabilities are loaded from a published active profile. The daemon only reloads when the active profile changes. Operators edit working profiles, validate them, and publish them explicitly.

**Tech Stack:** Python 3.x, httpx, PyYAML, existing `nodes/common/poller.py`, argparse.

---

## Files and Conventions

| Path | Purpose |
|------|---------|
| `~/.relay/ai-relay-agent.json` | Node metadata: `node_id`, `registration_secret`, `capabilities`, `base_url`. |
| `~/.relay/ai-relay-agent.token` | Current runtime token. |
| `~/.relay/relay_config.json` | Intervals, timeouts, log level. |
| `~/.relay/capabilities.d/<profile>.yaml` | Working profile files. Edit these freely. |
| `~/.relay/capabilities.active.yaml` | Published/active profile. Daemon reads only this. |
| `~/.relay/capabilities.active.profile` | Name of the currently active profile (plain text). |
| `~/.relay/node-cli.pid` | PID file for running daemon. |
| `~/.relay/node-cli.log` | Daemon log file. |
| `~/.relay/worker_status.json` | Last known worker status. |

---

## Capability Profile Format

`~/.relay/capabilities.d/default.yaml`:

```yaml
capabilities:
  - name: chat.ai
    version: "1.0.0"
    auto_publish: true
    claimable: true
    handler: /opt/relay/handlers/chat-ai.sh
    max_parallel: 2
    timeout: 300

  - name: storage.archive.native
    version: "1.0.0"
    auto_publish: true
    claimable: true
    handler: /opt/relay/handlers/archive.sh
    max_parallel: 1
    timeout: 600

  - name: mflux
    version: "1.0.0"
    auto_publish: true
    claimable: false
```

Rules:
- `auto_publish: true` → included in every heartbeat.
- `claimable: true` → daemon may claim stages for this capability.
- `handler` → required for `claimable: true`. Path or shell command.
- `max_parallel` → default 1. Per-capability in-flight limit.
- `timeout` → handler timeout in seconds. Default 300.

---

## Push Model

The daemon never reads unvalidated working files.

```
Operator edits  →  validate  →  publish  →  daemon sees active profile
working profile       profile      profile      at next heartbeat
```

- `~/.relay/capabilities.d/*.yaml` = working profiles. Safe to edit. No runtime effect.
- `~/.relay/capabilities.active.yaml` = published profile. Daemon loads only this.
- `~/.relay/capabilities.active.profile` = name of active profile.

Publishing:
1. Parse selected working profile.
2. Validate structure and constraints.
3. If valid: atomically copy to `capabilities.active.yaml`, update `capabilities.active.profile`.
4. Send `SIGHUP` to running daemon so it reloads immediately.
5. If invalid: print error, do not touch active profile.

Daemon behavior on active profile:
- On startup: load active profile. If missing or invalid, daemon starts with empty capabilities and logs error.
- During runtime: check `mtime` of `capabilities.active.yaml` each heartbeat. If changed, validate and reload.
- If reload fails: keep last valid capabilities, log error.

---

## Capability Validation Rules

A profile is invalid if any of these are true:
- YAML syntax error.
- `capabilities` key missing or not a list.
- Any capability missing `name`.
- Duplicate capability names.
- `claimable: true` and `handler` missing or empty.
- `max_parallel` not a positive integer.
- `timeout` not a positive integer.
- `auto_publish` or `claimable` not boolean.

Validation errors are printed with file and line context if available.

---

## Handler Contract

A handler is a subprocess (script, binary, hermes call, docker run, etc.).

**Env variables set by the CLI before execution:**
- `RELAY_STAGE_ID`
- `RELAY_TASK_ID`
- `RELAY_CAPABILITY`
- `RELAY_NODE_ID`
- `RELAY_BASE_URL`
- `RELAY_TOKEN_FILE` (path to current runtime token file)

**Stdin:** the stage `payload` as JSON.

**Stdout:** result JSON. Must be valid JSON.

**Stderr:** captured and included in error result if exit code != 0.

**Exit code:**
- `0` → stdout parsed as result, sent to `/relay/v2/scheduler/stages/{stage_id}/complete`.
- non-zero → `{"error": "handler exited with code N", "stderr": "..."}` sent as result.

**Timeout:** if handler exceeds `timeout`, terminate and send `{"error": "handler timeout after Ns"}`.

---

## CLI Commands

```bash
node-cli daemon start          # start background daemon
node-cli daemon stop           # stop daemon via PID file
node-cli daemon status         # show daemon PID, active profile, last heartbeat
node-cli daemon restart        # stop + start
node-cli daemon foreground     # run daemon in foreground (for systemd/docker)

node-cli heartbeat             # single heartbeat, foreground

node-cli claim <capability>    # single claim, print stage JSON to stdout
node-cli complete <stage_id> --task <task_id> --result-file <path>
node-cli task submit --name <name> --stage <capability>:<json_payload> [--priority N]

node-cli capabilities list                       # list working profiles
node-cli capabilities validate [<profile>]        # validate working profile (default: active)
node-cli capabilities publish <profile>          # publish profile to daemon
node-cli capabilities diff [<profile>]            # diff working vs active (default: active)
node-cli capabilities current                    # show active profile name

node-cli status                # print ~/.relay/worker_status.json
node-cli reload                # send SIGHUP to running daemon
```

The daemon writes:
- `~/.relay/node-cli.pid`
- `~/.relay/node-cli.log`
- `~/.relay/worker_status.json`

---

## Heartbeat Flow

1. Load `relay_config.json`.
2. Ensure runtime token (recover if missing).
3. Load published profile from `capabilities.active.yaml` with mtime cache.
4. Compute `load` via `os.getloadavg()[0]`, clamped to `[0.0, 1.0]`.
5. For each `auto_publish` capability, determine `available` based on current in-flight count vs `max_parallel`.
6. Send `POST /relay/v2/discovery/heartbeat`.
7. Update `worker_status.json` with result.
8. On 401/403, refresh/recover token and retry once.
9. Sleep `heartbeat_interval` seconds, repeat.

---

## Claim/Execute/Complete Flow

1. Every `claim_interval` seconds (default 5), load published profile.
2. For each `claimable` capability:
   - Skip if `in_flight[cap] >= max_parallel`.
   - Call `POST /relay/v2/scheduler/claim` with `{"capability": cap}`.
   - If no stage, continue.
3. Increment `in_flight[cap]`.
4. Spawn handler subprocess with env + stdin payload.
5. Capture stdout/stderr.
6. Call `POST /relay/v2/scheduler/stages/{stage_id}/complete` with result.
7. Decrement `in_flight[cap]`.
8. Update `tasks_completed` / `tasks_failed` counters.

The heartbeat thread and claim thread are independent. The heartbeat thread always runs, even while a long handler is executing.

---

## Capability Profile Loader with mtime Cache

`nodes/common/capability_loader.py`:

```python
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError:
    yaml = None

DEFAULTS = {
    "auto_publish": True,
    "claimable": True,
    "max_parallel": 1,
    "timeout": 300,
}

PROFILES_DIR = Path.home() / ".relay" / "capabilities.d"
ACTIVE_PATH = Path.home() / ".relay" / "capabilities.active.yaml"
ACTIVE_PROFILE_NAME_PATH = Path.home() / ".relay" / "capabilities.active.profile"


class CapabilityValidationError(Exception):
    pass


def _env_override_key(name: str, field: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]", "_", name).upper()
    return f"RELAY_CAPABILITY_{normalized}_{field.upper()}"


def _normalize_capability(raw: Any, index: int) -> Dict[str, Any]:
    if isinstance(raw, str):
        raw = {"name": raw}
    if not isinstance(raw, dict):
        raise CapabilityValidationError(f"capability[{index}] must be a mapping")
    if not raw.get("name"):
        raise CapabilityValidationError(f"capability[{index}] missing name")

    cap = {**DEFAULTS, **raw}

    env_handler = os.getenv(_env_override_key(cap["name"], "handler"))
    if env_handler:
        cap["handler"] = env_handler
    env_max_parallel = os.getenv(_env_override_key(cap["name"], "max_parallel"))
    if env_max_parallel:
        cap["max_parallel"] = int(env_max_parallel)

    # Type checks
    for field, expected in [("auto_publish", bool), ("claimable", bool)]:
        if not isinstance(cap[field], expected):
            raise CapabilityValidationError(
                f"capability[{index}] {field} must be {expected.__name__}"
            )
    for field in ("max_parallel", "timeout"):
        if not isinstance(cap[field], int) or cap[field] <= 0:
            raise CapabilityValidationError(
                f"capability[{index}] {field} must be a positive integer"
            )

    if cap["claimable"] and not cap.get("handler"):
        raise CapabilityValidationError(
            f"capability[{index}] {cap['name']} is claimable but has no handler"
        )

    return cap


def load_profile(path: Path) -> List[Dict[str, Any]]:
    if yaml is None:
        raise RuntimeError("PyYAML is required for capability configuration")
    if not path.exists():
        return []
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except Exception as exc:
        raise CapabilityValidationError(f"invalid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise CapabilityValidationError("profile root must be a mapping")
    caps = raw.get("capabilities")
    if caps is None:
        raise CapabilityValidationError("missing 'capabilities' key")
    if not isinstance(caps, list):
        raise CapabilityValidationError("'capabilities' must be a list")

    names = set()
    result = []
    for idx, c in enumerate(caps):
        cap = _normalize_capability(c, idx)
        if cap["name"] in names:
            raise CapabilityValidationError(f"duplicate capability name: {cap['name']}")
        names.add(cap["name"])
        result.append(cap)
    return result


def list_profiles() -> List[str]:
    if not PROFILES_DIR.exists():
        return []
    return sorted([p.stem for p in PROFILES_DIR.glob("*.yaml")])


def profile_path(name: str) -> Path:
    return PROFILES_DIR / f"{name}.yaml"


def get_active_profile_name() -> Optional[str]:
    if ACTIVE_PROFILE_NAME_PATH.exists():
        return ACTIVE_PROFILE_NAME_PATH.read_text().strip()
    return None


def set_active_profile_name(name: str):
    tmp = ACTIVE_PROFILE_NAME_PATH.with_suffix(".tmp")
    tmp.write_text(name + "\n")
    tmp.rename(ACTIVE_PROFILE_NAME_PATH)


def publish_profile(name: str):
    src = profile_path(name)
    caps = load_profile(src)
    tmp = ACTIVE_PATH.with_suffix(".tmp")
    tmp.write_text(yaml.safe_dump({"capabilities": caps}, sort_keys=False))
    tmp.rename(ACTIVE_PATH)
    set_active_profile_name(name)


_active_caps_mtime: Optional[float] = None
_active_caps_cache: Optional[List[Dict[str, Any]]] = None


def load_active_profile() -> List[Dict[str, Any]]:
    global _active_caps_mtime, _active_caps_cache
    if not ACTIVE_PATH.exists():
        _active_caps_mtime = None
        _active_caps_cache = []
        return []
    mtime = ACTIVE_PATH.stat().st_mtime
    if _active_caps_cache is not None and mtime == _active_caps_mtime:
        return _active_caps_cache
    caps = load_profile(ACTIVE_PATH)
    _active_caps_cache = caps
    _active_caps_mtime = mtime
    return caps


def invalidate_active_profile_cache():
    global _active_caps_mtime, _active_caps_cache
    _active_caps_mtime = None
    _active_caps_cache = None
```

---

## Env Overrides

Any value in `relay_config.json` or profile entries can be overridden via environment variables:

- `RELAY_BASE_URL`
- `RELAY_HEARTBEAT_INTERVAL`
- `RELAY_CLAIM_INTERVAL`
- `RELAY_PROFILES_DIR`
- `RELAY_CAPABILITY_<NAME>_HANDLER`
- `RELAY_CAPABILITY_<NAME>_MAX_PARALLEL`
- `RELAY_LOG_LEVEL`

`<NAME>` is uppercased and dots/underscores normalized.

---

## CLI Behavior Details

### `node-cli capabilities publish <profile>`

1. Load and validate `~/.relay/capabilities.d/<profile>.yaml`.
2. If invalid: print error and exit with code 1. Active profile stays unchanged.
3. If valid: atomically write to `~/.relay/capabilities.active.yaml` and update `~/.relay/capabilities.active.profile`.
4. If daemon PID file exists and process is running: send `SIGHUP`.
5. Print success.

### `node-cli capabilities validate [<profile>]`

- If `profile` omitted: validate currently active profile (or active profile name if file exists).
- Print validation errors or “valid”.

### `node-cli daemon start`

1. Check if daemon already running via PID file.
2. If running: print status and exit.
3. Spawn detached subprocess with hidden `--daemon-internal` flag.
4. Internal process:
   - Load config.
   - Recover token if needed.
   - Load active profile (or empty if missing).
   - Start heartbeat thread.
   - Start claim loop.
   - Write PID file.
   - Set up signal handlers for `SIGTERM`/`SIGINT` (shutdown) and `SIGHUP` (reload active profile).

### `node-cli daemon foreground`

Same as internal daemon mode but stays attached to terminal. Useful for systemd/docker.

### `node-cli reload`

Read PID file, send `SIGHUP` if process exists.

---

## Task Breakdown

### Task 1: Create `nodes/common/capability_loader.py`

**Objective:** Profile loader with validation, publish, and active-profile cache.

**Files:**
- Create: `nodes/common/capability_loader.py`
- Test: `tests/test_capability_loader.py`

**Step 1: Write failing test**

```python
def test_load_profile_returns_normalized_list(tmp_path):
    caps_file = tmp_path / "default.yaml"
    caps_file.write_text(textwrap.dedent("""
        capabilities:
          - name: chat.ai
            version: "1.0.0"
            auto_publish: true
            claimable: true
            handler: /bin/echo
            max_parallel: 2
            timeout: 300
    """))
    caps = load_profile(caps_file)
    assert len(caps) == 1
    assert caps[0]["name"] == "chat.ai"
    assert caps[0]["max_parallel"] == 2


def test_load_profile_rejects_claimable_without_handler(tmp_path):
    caps_file = tmp_path / "bad.yaml"
    caps_file.write_text(textwrap.dedent("""
        capabilities:
          - name: chat.ai
            claimable: true
    """))
    with pytest.raises(CapabilityValidationError):
        load_profile(caps_file)


def test_publish_profile_creates_active_file(tmp_path, monkeypatch):
    monkeypatch.setattr(capability_loader, "PROFILES_DIR", tmp_path)
    monkeypatch.setattr(capability_loader, "ACTIVE_PATH", tmp_path / "active.yaml")
    monkeypatch.setattr(capability_loader, "ACTIVE_PROFILE_NAME_PATH", tmp_path / "active.profile")
    (tmp_path / "default.yaml").write_text("capabilities:\n  - name: chat.ai\n    handler: /bin/echo\n")
    publish_profile("default")
    assert (tmp_path / "active.yaml").exists()
    assert (tmp_path / "active.profile").read_text().strip() == "default"
```

**Step 2: Run test to verify failure**

```bash
pytest tests/test_capability_loader.py -v
```

Expected: FAIL.

**Step 3: Implement loader**

Use the module code shown in the Capability Profile Loader section.

**Step 4: Run test**

```bash
pytest tests/test_capability_loader.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add nodes/common/capability_loader.py tests/test_capability_loader.py
git commit -m "feat(node-cli): capability profile loader with validation and publish"
```

---

### Task 2: Create `nodes/common/handler_runner.py`

**Objective:** Execute a capability handler subprocess with env + stdin JSON, capture result, enforce timeout.

**Files:**
- Create: `nodes/common/handler_runner.py`
- Test: `tests/test_handler_runner.py`

**Step 1: Write failing test**

```python
def test_run_handler_success():
    result = run_handler(
        handler="/bin/cat",
        stage={"stage_id": "s1", "task_id": "t1", "capability": "chat.ai", "payload": {"x": 1}},
        node_id="N1",
        base_url="http://localhost:8788",
        token_file=Path("/tmp/token"),
        timeout=10,
    )
    assert result == {"x": 1}
```

**Step 2: Run test to verify failure**

```bash
pytest tests/test_handler_runner.py -v
```

Expected: FAIL.

**Step 3: Implement runner**

```python
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict


def _build_env(stage: Dict[str, Any], node_id: str, base_url: str, token_file: Path) -> Dict[str, str]:
    env = os.environ.copy()
    env.update({
        "RELAY_STAGE_ID": stage.get("stage_id", ""),
        "RELAY_TASK_ID": stage.get("task_id", ""),
        "RELAY_CAPABILITY": stage.get("capability", ""),
        "RELAY_NODE_ID": node_id,
        "RELAY_BASE_URL": base_url,
        "RELAY_TOKEN_FILE": str(token_file),
    })
    return env


def run_handler(handler: str, stage: Dict[str, Any], node_id: str, base_url: str, token_file: Path, timeout: int) -> Dict[str, Any]:
    env = _build_env(stage, node_id, base_url, token_file)
    payload_json = json.dumps(stage.get("payload", {}))
    try:
        proc = subprocess.run(
            handler,
            input=payload_json,
            env=env,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"error": f"handler timeout after {timeout}s"}

    if proc.returncode != 0:
        return {"error": f"handler exited with code {proc.returncode}", "stderr": proc.stderr.strip()}

    try:
        return json.loads(proc.stdout) if proc.stdout.strip() else {"status": "ok"}
    except json.JSONDecodeError:
        return {"error": "handler output is not valid JSON", "stdout": proc.stdout}
```

**Step 4: Run test**

```bash
pytest tests/test_handler_runner.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add nodes/common/handler_runner.py tests/test_handler_runner.py
git commit -m "feat(node-cli): subprocess handler runner with env and timeout"
```

---

### Task 3: Create `nodes/common/node_cli.py` — CLI Skeleton

**Objective:** Argparse entry point with all subcommands. No full implementation yet; just parse and dispatch.

**Files:**
- Create: `nodes/common/node_cli.py`
- Modify: `pyproject.toml` to add entry point `node-cli = nodes.common.node_cli:main`
- Test: `tests/test_node_cli.py`

**Step 1: Write failing test**

```python
def test_cli_help():
    result = subprocess.run(["python", "-m", "nodes.common.node_cli", "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "daemon" in result.stdout
    assert "capabilities" in result.stdout
```

**Step 2: Run test to verify failure**

```bash
pytest tests/test_node_cli.py -v
```

Expected: FAIL.

**Step 3: Implement skeleton**

```python
import argparse
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(prog="node-cli", description="Generic AI Relay node CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    daemon = sub.add_parser("daemon", help="daemon control")
    daemon.add_argument("action", choices=["start", "stop", "status", "restart", "foreground"])

    sub.add_parser("heartbeat", help="send a single heartbeat")
    claim = sub.add_parser("claim", help="claim one stage")
    claim.add_argument("capability")
    complete = sub.add_parser("complete", help="complete a stage")
    complete.add_argument("stage_id")
    complete.add_argument("--task", required=True)
    complete.add_argument("--result-file", required=True)

    task = sub.add_parser("task", help="task operations")
    task_sub = task.add_subparsers(dest="task_action", required=True)
    submit = task_sub.add_parser("submit", help="submit a task")
    submit.add_argument("--name", required=True)
    submit.add_argument("--stage", action="append", required=True)
    submit.add_argument("--priority", type=int, default=0)

    caps = sub.add_parser("capabilities", help="manage capability profiles")
    caps_sub = caps.add_subparsers(dest="caps_action", required=True)
    caps_sub.add_parser("list", help="list working profiles")
    validate = caps_sub.add_parser("validate", help="validate a profile")
    validate.add_argument("profile", nargs="?")
    publish = caps_sub.add_parser("publish", help="publish a profile")
    publish.add_argument("profile")
    diff = caps_sub.add_parser("diff", help="diff working vs active profile")
    diff.add_argument("profile", nargs="?")
    caps_sub.add_parser("current", help="show active profile name")

    sub.add_parser("status", help="show worker status")
    sub.add_parser("reload", help="reload capabilities in running daemon")

    args = parser.parse_args(argv)
    print(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

**Step 4: Run test**

```bash
pytest tests/test_node_cli.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add nodes/common/node_cli.py tests/test_node_cli.py pyproject.toml
git commit -m "feat(node-cli): argparse skeleton with daemon and capability commands"
```

---

### Task 4: Implement `capabilities` Subcommands

**Objective:** `list`, `validate`, `publish`, `diff`, `current` work end-to-end.

**Files:**
- Modify: `nodes/common/node_cli.py`
- Test: `tests/test_node_cli.py`

**Step 1: Write failing test**

```python
def test_capabilities_publish(tmp_path):
    # Setup profile dir, active paths via monkeypatch
    ...
    result = subprocess.run([...], capture_output=True, text=True)
    assert result.returncode == 0
    assert (tmp_path / "capabilities.active.yaml").exists()
```

**Step 2: Implement**

Add `cmd_capabilities(args)`:
- `list`: print profile names.
- `validate`: load profile, print errors or valid.
- `publish`: validate, atomically copy to active, update active profile name, send SIGHUP if daemon running.
- `diff`: load both profiles, print YAML diff or message.
- `current`: print active profile name.

**Step 3: Run test**

```bash
pytest tests/test_node_cli.py::test_capabilities -v
```

Expected: PASS.

**Step 4: Commit**

```bash
git commit -am "feat(node-cli): capability profile management commands"
```

---

### Task 5: Implement `heartbeat` and `status` Subcommands

**Objective:** Send a single heartbeat and print status.

**Files:**
- Modify: `nodes/common/node_cli.py`
- Test: `tests/test_node_cli.py`

**Step 1: Write failing test**

Use the FastAPI test client to mock a relay server. Test that `node-cli heartbeat` succeeds.

**Step 2: Implement**

Add `cmd_heartbeat(args)` that:
- Loads meta + config.
- Loads active profile via `capability_loader.load_active_profile()`.
- Calls `poller.heartbeat()`.
- Prints JSON result.

Add `cmd_status(args)` that prints `worker_status.json` if it exists.

**Step 3: Run test**

```bash
pytest tests/test_node_cli.py -v
```

Expected: PASS.

**Step 4: Commit**

```bash
git commit -am "feat(node-cli): heartbeat and status subcommands"
```

---

### Task 6: Implement `daemon start` and `daemon foreground`

**Objective:** Start a daemon that sends heartbeats forever in a background thread.

**Files:**
- Modify: `nodes/common/node_cli.py`
- Test: `tests/test_node_cli.py` (start daemon, verify PID file, send signal, check status)

**Step 1: Write failing test**

Start daemon against a test relay, verify heartbeat arrives.

**Step 2: Implement**

- `cmd_daemon_start(args)` checks PID file, spawns detached subprocess with hidden `--daemon-internal` flag.
- `--daemon-internal` mode:
  - Load config.
  - Recover token if needed.
  - Load active profile.
  - Start heartbeat thread.
  - Write PID file.
  - Set up `SIGTERM`/`SIGINT` (shutdown), `SIGHUP` (reload active profile).
- `cmd_daemon_foreground(args)` runs the same internal loop but attached.

For simplicity and portability, use self-spawn:
  - `node-cli daemon start` calls `subprocess.Popen([sys.executable, "-m", "nodes.common.node_cli", "--daemon-internal"], ...)` with stdout/stderr redirected to log file.

**Step 3: Run test**

```bash
pytest tests/test_node_cli.py -v
```

Expected: PASS.

**Step 4: Commit**

```bash
git commit -am "feat(node-cli): daemon mode with background heartbeat"
```

---

### Task 7: Implement Claim Loop in Daemon

**Objective:** Daemon claims stages for all `claimable` capabilities and dispatches handlers.

**Files:**
- Modify: `nodes/common/node_cli.py`
- Modify: `nodes/common/poller.py` if needed (ensure `claim` returns stage or None).
- Test: `tests/test_node_cli.py`

**Step 1: Write failing test**

Submit a task to test relay, start daemon with a simple `echo` handler, verify task completes.

**Step 2: Implement**

In daemon internal loop:
- Every `claim_interval` seconds, reload active profile.
- For each `claimable` cap where `in_flight[cap] < max_parallel`:
  - `poller.claim(cap)`.
  - If stage returned, run handler via `handler_runner.run_handler`.
  - `poller.complete(...)` with result.
  - Update counters.

Heartbeat thread and claim thread must be independent. Use threading.Lock for shared state (`token`, `in_flight`, counters).

**Step 3: Run test**

```bash
pytest tests/test_node_cli.py -v
```

Expected: PASS.

**Step 4: Commit**

```bash
git commit -am "feat(node-cli): claim loop with handler dispatch"
```

---

### Task 8: Implement `claim`, `complete`, `task submit` Foreground Subcommands

**Objective:** Allow scripts to use CLI for single operations without daemon.

**Files:**
- Modify: `nodes/common/node_cli.py`
- Test: `tests/test_node_cli.py`

**Step 1: Write failing test**

Test `node-cli claim chat.ai`, `node-cli complete s1 --task t1 --result-file /tmp/result.json`, and `node-cli task submit --name test --stage 'chat.ai:{"q":"hi"}'`.

**Step 2: Implement**

- `cmd_claim`: call `poller.claim`, print stage JSON to stdout.
- `cmd_complete`: read result file, call `poller.complete`.
- `cmd_task_submit`: parse `--stage cap:json` pairs, call `poller.submit_task`.

**Step 3: Run test**

```bash
pytest tests/test_node_cli.py -v
```

Expected: PASS.

**Step 4: Commit**

```bash
git commit -am "feat(node-cli): foreground claim, complete, and task submit"
```

---

### Task 9: Add Entry Point and Documentation

**Objective:** Make `node-cli` installable and document it.

**Files:**
- Modify: `pyproject.toml` to add `[project.scripts]` entry `node-cli`.
- Modify: `docs/node-readme.md` to mention `node-cli` and capability profiles.
- Create: `nodes/common/README.node-cli.md` with examples.
- Test: `tests/test_node_cli.py` verify installed command.

**Step 1: Add entry point**

```toml
[project.scripts]
node-cli = "nodes.common.node_cli:main"
```

**Step 2: Install and test**

```bash
pip install -e .
node-cli --help
```

Expected: help text appears.

**Step 3: Update docs**

Add section in `docs/node-readme.md`:
- How to create `~/.relay/capabilities.d/default.yaml`.
- How to publish a profile.
- How to start daemon.
- How to write a handler.

**Step 4: Commit**

```bash
git commit -am "feat(node-cli): installable entry point and documentation"
```

---

## Verification

Full test run:

```bash
source .venv/bin/activate
ruff check nodes/common tests
pytest tests/ -q
```

Expected: all existing tests pass, new tests pass.

---

## Risks and Tradeoffs

1. **Subprocess handlers with shell=True.** Intentional flexibility, but handler strings must come from trusted sources. Only operators write profile files.
2. **Daemon detach portability.** Use self-spawn to avoid `python-daemon` dependency.
3. **JSON-only handler contract.** Language-agnostic; operators must ensure valid JSON output.
4. **Active profile is a single file.** Only one profile active at a time. To combine capabilities, create a new profile.
5. **No automatic profile fallback.** If active profile becomes invalid after publication, daemon keeps last valid capabilities. Fix requires re-publishing a valid profile.

---

## Open Questions

1. Should `node-cli capabilities publish` support `--no-reload` to skip SIGHUP?
2. Should the daemon reload active profile immediately on `SIGHUP` even if mtime did not change?
3. Should handlers receive the full stage object (including `stage_id`) in stdin instead of only `payload`?
4. Should `node-cli` support a global `--config` flag to override `~/.relay/` paths?
