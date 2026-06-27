# Node-CLI & Daemon for AI-Relay-Service

> **Scope:** Build a generic `node-cli` command-line tool that runs as a daemon (heartbeat + claim/complete loop) or foreground process. All capabilities are defined in external YAML profiles — the CLI itself is capability-agnostic.
>
> **Context:** This is for the `ai-relay-service` project at `/home/felix/projects/ai-relay-service`. The server code lives under `src/relay_server/`, existing node code under `nodes/`, and the relay client library at `relay_client/`.

---

## 0. Prerequisites & Context Files

These files exist and should be read before starting implementation:

| File | Purpose |
|------|---------|
| `src/relay_server/api/v2/discovery.py` | Server discovery & heartbeat API (POST `/relay/v2/discovery/heartbeat`, POST `/relay/v2/scheduler/claim`, POST `/relay/v2/scheduler/stages/{id}/complete`) |
| `nodes/common/poller.py` | Existing Python library wrapping relay HTTP calls (heartbeat, claim, complete, get_nodes, etc.) |
| `nodes/common/capability.py` | Server-side capability model (CapabilityInputField, CapabilityInputSchema) |
| `nodes/storage-node/storage_node.py` | Example of a specific node implementation |
| `nodes/worker/worker.py` | Example worker node with CLI |
| `src/relay_server/models/task.py` | Task model including `validate_simple_task()` |
| `src/relay_server/models/__init__.py` | Re-exports CapabilityInputSchema |
| `docs/node-readme.md` | Node documentation (may be outdated) |
| `BUILDING.md` | Project build/roadmap doc |

---

## 1. Goals & Deliverables

### Files to Create

| File | Description |
|------|-------------|
| `nodes/common/capability_loader.py` | Load, validate, and publish capability profiles from YAML |
| `nodes/common/handler_runner.py` | Execute capability handler as subprocess with env/stdin/timeout |
| `nodes/common/node_cli.py` | Main CLI entry point with argparse subcommands |
| `tests/test_capability_loader.py` | Tests for capability_loader |
| `tests/test_handler_runner.py` | Tests for handler_runner |
| `tests/test_node_cli.py` | Tests for the CLI (skeleton + integration) |

### Files to Modify

| File | Change |
|------|--------|
| `pyproject.toml` | Add `[project.scripts] node-cli = "nodes.common.node_cli:main"` |
| `docs/node-readme.md` | Add sections for `node-cli` usage, profile config, handler examples |

---

## 2. File & Directory Layout

```
~/.relay/
├── ai-relay-agent.json            # Node metadata (already exists)
├── ai-relay-agent.token           # Runtime token (already exists)
├── relay_config.json              # Config: intervals, base_url, log level (already exists)
├── capabilities.d/                # Working profiles (directory may not exist yet)
│   └── default.yaml
├── capabilities.active.yaml       # Published/active profile (daemon reads only this)
├── capabilities.active.profile    # Name of currently active profile (plain text)
├── node-cli.pid                   # Daemon PID file
├── node-cli.log                   # Daemon log output
└── worker_status.json             # Last heartbeat result
```

---

## 3. Capability Profile YAML Format

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

**Rules:**
- `auto_publish: true` → included in every heartbeat as available capability
- `claimable: true` → daemon may claim stages for this capability
- `handler` → **required** when `claimable: true`. Path to executable or shell command.
- `max_parallel` → default `1`. Per-capacity in-flight handler limit.
- `timeout` → handler timeout in seconds. Default `300`.

---

## 4. Handler Contract

A handler is an external subprocess (script, binary, etc.).

**Environment variables set before execution:**

| Variable | Value |
|----------|-------|
| `RELAY_STAGE_ID` | Stage ID from claim |
| `RELAY_TASK_ID` | Task ID from claim |
| `RELAY_CAPABILITY` | Capability name |
| `RELAY_NODE_ID` | Assigned node ID |
| `RELAY_BASE_URL` | Relay server URL |
| `RELAY_TOKEN_FILE` | Path to runtime token file |

**Stdin:** Stage `payload` as JSON string.

**Stdout:** Must be valid JSON — the result sent to `/complete` endpoint.

**Stderr:** Captured and included in error result if exit code != 0.

**Exit codes:**
- `0` → stdout parsed as result dict, sent to complete endpoint
- non-zero → `{"error": "handler exited with code N", "stderr": "..."}`

**Timeout:** If handler exceeds timeout, terminate subprocess and return `{"error": "handler timeout after Ns"}`.

---

## 5. CLI Commands

```bash
# Daemon control
node-cli daemon start          # start daemon in background
node-cli daemon stop           # stop via PID file
node-cli daemon status         # show PID, active profile, last heartbeat
node-cli daemon restart        # stop + start
node-cli daemon foreground     # run in foreground (for systemd/Docker)

# One-shot operations
node-cli heartbeat             # single heartbeat (foreground)
node-cli claim <capability>    # claim one stage, print JSON to stdout
node-cli complete <stage_id> --task <task_id> --result-file <path>
node-cli task submit --name <name> --stage <cap>:<json_payload> [--priority N]

# Capability profile management
node-cli capabilities list                        # list profiles in capabilities.d/
node-cli capabilities validate [profile]          # validate a profile (default: active)
node-cli capabilities publish <profile>           # validate + atomically copy to active + SIGHUP daemon
node-cli capabilities diff [profile]              # diff working profile vs active
node-cli capabilities current                     # show active profile name

# Status
node-cli status                # print worker_status.json content
node-cli reload                # send SIGHUP to running daemon
```

---

## 6. Architecture

### Push Model (Capability Profiles)

```
Operator edits ~/.relay/capabilities.d/default.yaml
        ↓
node-cli capabilities validate default    ← validates without touching active
        ↓
node-cli capabilities publish default     ← validates + atomic write to active.yaml
        ↓
Daemon picks up change at next heartbeat (mtime check) or via SIGHUP
```

**Key invariant:** The daemon only reads `capabilities.active.yaml`. Working profiles in `capabilities.d/` are never read by the daemon.

### Daemon Internals

```
┌─────────────────────────────────────────────┐
│              node-cli daemon                 │
│                                              │
│  ┌─────────────┐    ┌──────────────────┐    │
│  │ Heartbeat    │    │ Claim Loop       │    │
│  │ Thread       │    │ Thread           │    │
│  │              │    │                   │    │
│  │ every 8s:    │    │ every 5s:        │    │
│  │ load active  │    │ for each claimable│   │
│  │ profile      │    │   cap:           │    │
│  │ send heartbeat│   │   if in_flight < │    │
│  │ to server    │    │     max_parallel:│    │
│  │              │    │   spawn handler  │    │
│  │ on 401/403:  │    │   wait for result│   │
│  │ refresh token│   │   complete stage  │    │
│  └─────────────┘    └──────────────────┘    │
│                                              │
│  Shared state (with locks):                 │
│  - token, in_flight, tasks_completed/failed │
└─────────────────────────────────────────────┘
```

### Heartbeat Flow

1. Load `relay_config.json`
2. Ensure runtime token (recover if missing/expired)
3. Load active profile via `load_active_profile()` (with mtime cache)
4. Compute `load` via `os.getloadavg()[0]`, clamped to `[0.0, 1.0]`
5. For each `auto_publish` capability, set `available` based on `in_flight` vs `max_parallel`
6. Send POST `/relay/v2/discovery/heartbeat`
7. Update `worker_status.json` with result
8. On 401/403 → refresh/recover token and retry once
9. Sleep `heartbeat_interval`, repeat

### Claim/Execute/Complete Flow

1. Every `claim_interval` seconds (default 5), reload active profile
2. For each `claimable` capability:
   - Skip if `in_flight[cap] >= max_parallel`
   - POST `/relay/v2/scheduler/claim` with `{"capability": cap}`
   - If no stage returned, continue
3. Increment `in_flight[cap]`
4. Spawn handler subprocess (env + stdin JSON)
5. Wait for result (with timeout)
6. POST `/relay/v2/scheduler/stages/{stage_id}/complete` with result
7. Decrement `in_flight[cap]`
8. Update `tasks_completed` / `tasks_failed` counters

### mtime Cache for Capabilities

```python
# Before each heartbeat/claim-loop iteration:
mtime = ACTIVE_PATH.stat().st_mtime
if mtime != _cached_mtime:
    _cached_caps = load_profile(ACTIVE_PATH)
    _cached_mtime = mtime
return _cached_caps
```

### Signal Handling

- `SIGTERM` / `SIGINT` → graceful shutdown (set shutdown event, wait for threads)
- `SIGHUP` → invalidate capability cache, reload active profile on next loop iteration

---

## 7. Environment Variable Overrides

| Variable | Overrides |
|----------|-----------|
| `RELAY_BASE_URL` | Server URL |
| `RELAY_HEARTBEAT_INTERVAL` | Heartbeat interval in seconds |
| `RELAY_CLAIM_INTERVAL` | Claim loop interval in seconds |
| `RELAY_PROFILES_DIR` | Path to profiles directory |
| `RELAY_LOG_LEVEL` | Log level (DEBUG/INFO/WARNING/ERROR) |
| `RELAY_CAPABILITY_<NAME>_HANDLER` | Override handler for specific capability |
| `RELAY_CAPABILITY_<NAME>_MAX_PARALLEL` | Override max_parallel |

`<NAME>` is uppercased with dots/underscores normalized to underscores.

---

## 8. Validation Rules for Profiles

A profile is **invalid** if any of these are true:
- YAML syntax error
- `capabilities` key missing or not a list
- Any capability missing `name`
- Duplicate capability names
- `claimable: true` and `handler` missing or empty
- `max_parallel` not a positive integer
- `timeout` not a positive integer
- `auto_publish` or `claimable` not boolean

On validation error: print error with context (file, line), do **not** touch active profile.

---

## 9. Daemon Detach Strategy

Use self-spawn (no `python-daemon` dependency):

1. `node-cli daemon start` checks PID file
2. If already running → print status, exit
3. Spawns: `subprocess.Popen([sys.executable, "-m", "nodes.common.node_cli", "--daemon-internal"], stdout=log, stderr=log, start_new_session=True)`
4. Inner process (`--daemon-internal` flag) runs the actual loops
5. Writes PID file after successful startup

For Docker/systemd: `node-cli daemon foreground` runs the same loop attached to terminal.

---

## 10. Required Server Endpoints

The server must expose these (already implemented):

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/relay/v2/discovery/heartbeat` | Send capabilities + get status |
| POST | `/relay/v2/scheduler/claim` | Claim a stage for a capability |
| POST | `/relay/v2/scheduler/stages/{stage_id}/complete` | Complete a claimed stage |

Relevant server source code for reference:
- `src/relay_server/api/v2/discovery.py` — heartbeat + claim endpoint
- `src/relay_server/api/v2/scheduler.py` — stage completion endpoint
- `src/relay_server/core/scheduler.py` — scheduler logic

---

## 11. Testing Requirements

All new code must have tests. Run: `pytest tests/ -x -q`

### Test Files to Create

**`tests/test_capability_loader.py`:**
- Load valid profile → correct normalized dicts
- Load profile with missing `name` → `CapabilityValidationError`
- Load profile with claimable but no handler → `CapabilityValidationError`
- Load profile with duplicate names → error
- `publish_profile()` atomically writes active file
- `load_active_profile()` with mtime cache works

**`tests/test_handler_runner.py`:**
- Run `/bin/cat` handler → stdout returned as dict
- Handler with non-zero exit → error dict with stderr
- Handler timeout → timeout error dict
- Env vars correctly set

**`tests/test_node_cli.py`:**
- `node-cli --help` shows all subcommands
- `capabilities list` shows profiles
- `capabilities validate` detects bad profiles
- `capabilities publish` creates active file
- Parse all subcommands without errors

### Existing Test Baseline

The current test suite has **93 tests passing**. New tests must not break any existing tests.
- Run: `PYTHONPATH=src pytest tests/ -x -q`

---

## 12. Linting Requirements

- Run: `.venv/bin/ruff check nodes/common/ tests/ --select E,W,F,I,N`
- All checks must pass (no errors, no warnings)
- Code should follow existing project conventions (see verified files in repo)

---

## 13. Commit Convention

Use conventional commits:
```
feat(node-cli): capability profile loader with validation
feat(node-cli): handler runner with subprocess execution
feat(node-cli): CLI skeleton with all subcommands
fix(node-cli): ...
docs(node-cli): ...
test(node-cli): ...
```

---

## 14. Known Issues & Pre-existing Bugs

These are bugs found during spec preparation that OpenCode should be aware of:

### 14.1 `CapabilityInputSchema.from_dict()` — KeyError on `name`

**File:** `src/relay_server/models/capability.py` (line 61–63)

**Bug:** When `from_dict()` receives a dict-style fields definition like:

```python
{'topic': {'type': 'string', 'required': True}}
```

…the code iterated over `raw_fields.values()` and tried `raw["name"]`, which doesn't exist in dict-style entries (the key IS the name). This caused a `KeyError: 'name'`.

**Fix applied:** Changed iteration to `.items()`, using the dict key as fallback name:

```python
name = raw.get("name") or key
```

For list-style input (the original path), a generated `field_N` key is used as fallback.

**Also fixed:** Pyright type error — `raw.get("name")` returns `str | None`, which isn't assignable to the `name: str` parameter. The `or key` fallback guarantees a non-None string in the dict case; for the list case, a fallback key `field_N` is provided.

---

## 15. Open Questions & Design Decisions

1. Handler receives only `payload` on stdin, not the full stage object — this is intentional for simplicity. Handlers that need the full stage can read env vars (`RELAY_STAGE_ID`, etc.).
2. The daemon uses threading (not asyncio) to keep it simple and compatible with blocking subprocess calls.
3. No retry on `complete` failure — rely on the poller's token-error retry first. Retry can be added later.
4. Profiles use YAML, not JSON, because YAML is more human-friendly for editing config files.
5. The Push Model (separate working vs active profiles) prevents the daemon from loading a half-edited file.

---

## 16. Deliverable: Final Report (Template for OpenCode)

After completing all tasks, provide a **Final Report** as a separate Markdown file (`REPORT_NODE_CLI.md`). The report must cover:

### Report Structure

```markdown
# Node-CLI & Daemon — Final Report

## Summary
- What was implemented (files created, files modified)
- What was NOT implemented (and why)
- Any deviations from this spec

## Implementation Details

### Architecture Decisions
- Any changes from the spec made during implementation (with rationale)
- Trade-offs accepted

### File Inventory
| File | Lines | Purpose | Status |
|------|-------|---------|--------|
| `nodes/common/capability_loader.py` | | Load/validate/publish profiles | Implemented / Partial / Skipped |
| `nodes/common/handler_runner.py` | | Subprocess handler execution | ... |
| `nodes/common/node_cli.py` | | CLI entry point + all subcommands | ... |
| `tests/test_capability_loader.py` | | ... | ... |
| `tests/test_handler_runner.py` | | ... | ... |
| `tests/test_node_cli.py` | | ... | ... |

### Known Issues
- Bugs found during implementation (with reproduction steps)
- Workarounds applied
- Issues deferred to future work

### Pre-existing Bugs Found
- `CapabilityInputSchema.from_dict()` KeyError (already fixed in `0898380`)
- Any new bugs discovered while building

### Test Coverage
- Total tests: X passed, Y failed, Z skipped
- New tests written: N
- Existing tests still passing: verify with `PYTHONPATH=src pytest tests/ -q`

### Linting
- ruff check output (clean or list of remaining warnings)

### Security Considerations
- Handler subprocesses use `shell=True` — risk assessment
- Profile files are trusted-operator-only — documented
- Token handling (file-based, not in memory longer than needed)

## Open Questions (Updated)
- Which questions from §15 were resolved?
- New questions discovered during implementation?

## Recommendations for Next Steps
- What should be done after this PR is merged
- Priority order for remaining tasks
```

### Verification Checklist (must be TRUE before submitting)

- [ ] `ruff check nodes/common/ tests/ --select E,W,F,I,N` → 0 errors
- [ ] `PYTHONPATH=src pytest tests/ -q` → all existing tests pass + new tests pass
- [ ] All 9 CLI subcommands from §5 are functional
- [ ] Daemon starts, heartbeats, and claims at least one stage end-to-end
- [ ] Profile publish/validate/list/diff/current all work
- [ ] Handler runner subprocess execution works with correct env/stdin/stdout/timeout
- [ ] Report file `REPORT_NODE_CLI.md` exists in repo root or PR description
- [ ] No secrets or credentials in any committed file

---

## 15. Open Questions & Design Decisions