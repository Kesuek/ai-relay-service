# Building Plan – ai-relay-service

> Central reference for the current development status and the next steps.
> Updated: 2026-06-26

---

## Project overview

- **Repo:** `~/projects/ai-relay-service`
- **Branch:** `master` (clean after commit `4544b65`)
- **Build:** `pip install -e .` in the venv `.venv`
- **Start server:** `relay-server` (entrypoint: `relay_server.main:main`)
- **Start worker:** `relay-worker start` (upcoming)
- **Tests:** `pytest` → currently 43/43 green

---

## Architecture decisions (currently final)

| # | Decision | Status |
|---|-----------|--------|
| AD-1 | Input schema: flexible as `dict`, validation via `CapabilityInputSchema` | ✅ |
| AD-2 | Capability classes: server (`models/`) + worker (`nodes/common/`) separated, but compatible | ✅ |
| AD-3 | Validation: CLI locally (UX) + worker (authority), server only basic check | ✅ |
| AD-4 | Capability API endpoints in `discovery.py` | ✅ |
| AD-5 | Atomic write for `capabilities.yaml` (CLI) + mtime check (daemon) | ✅ |
| AD-6 | Heartbeat every 8s, no file read per heartbeat, only on mtime change or SIGHUP | ✅ |

---

## Current status

### ✅ Completed

| Area | What | Where |
|---------|-----|----|
| Server API | Auth v2, SlowAPI, dashboard, CSRF, security headers | `src/relay_server/` |
| Database | SQLite, `nodes` table with `capabilities` JSON column | `src/relay_server/core/db.py` |
| Scheduler | Task phase system, claim/release/complete, DAG stages | `src/relay_server/api/v2/scheduler.py` |
| Node capabilities | `CapabilitySet`, `Capability` dataclass, YAML load | `nodes/common/capability.py` |
| Worker daemon | Registration, heartbeat loop, graceful shutdown, CLI stub | `nodes/worker/worker.py` |
| Capability template | Example `capabilities.yaml` with `script.image.flux` | `nodes/worker/capabilities.yaml` |

### 🔄 In progress

| Area | What | Status |
|---------|-----|--------|
| Data models (new) | `models/capability.py` (InputField + schema + validation) | ✅ written |
| Data models (new) | `models/discovery.py` (DiscoveryNode, DiscoveryCapability) | ✅ written |
| Data models (new) | `models/task.py` (SimpleTaskRequest, idempotency) | ✅ written |
| models/__init__.py | Cleanup: replace old Capability, import new ones | ⬜ open |

### ⬜ Not yet started

| Area | What | Prio |
|---------|-----|------|
| Server discovery API | `GET /capabilities`, `GET /capabilities/{name}` | 🔴 P0 |
| Server simple task | `POST /scheduler/task-simple` | 🔴 P0 |
| Worker input validator | Validate payload against input schema | 🔴 P0 |
| Worker token refresh | Credential refresh before expiry | 🔴 P0 |
| Worker artifact download | Fetch input artifacts before a stage | 🟡 P1 |
| Worker SIGHUP + mtime | Reload capabilities at runtime | 🟡 P1 |
| Worker reconnect | Auto-reconnect + re-register | 🟡 P1 |
| CLI caps write | Atomic write + validate | 🔴 P0 |
| CLI task submit | Submit a task with server discovery | 🔴 P0 |
| CLI caps validate | Schema validation (local) | 🟡 P1 |
| CLI caps show | Display capabilities (local/server) | 🟢 P2 |
| CLI task watch | Live-follow a task | 🟢 P2 |
| CLI config | Manage `~/.relay/config.json` | 🟡 P1 |

---

## Coding session workflow (following the opencode-run pattern)

### Create new files

```
opencode run --agent primary "Create the file models/__init__.py with all Pydantic models.
The old Capability/Task models in the file must be replaced by the new ones from models/capability.py,
models/discovery.py and models/task.py. Import everything cleanly and make sure
existing imports from api/v2/auth.py and api/v2/scheduler.py keep working."
```

### Extend existing server endpoints

```
opencode run --agent primary "Extend src/relay_server/api/v2/discovery.py with two new GET endpoints:
1. GET /capabilities - returns DiscoveryResponse (all capabilities of all nodes)
2. GET /capabilities/{name} - returns DiscoveryDetailResponse

The data comes from the SQLite nodes table, capabilities JSON column.
Merging: the same capability name from different nodes becomes one entry with a nodes array."
```

### Extend the worker daemon

```
opencode run --agent primary "Extend nodes/worker/worker.py with:
1. Input validation before task execution against CapabilityInputSchema
2. mtime check in the heartbeat loop: check os.path.getmtime(), reload on change
3. SIGHUP handler: reload capabilities.yaml + send a heartbeat immediately
4. Error handling: log an exception for an invalid capability, mark the stage as failed

Use nodes/common/capability.py for CapabilitySet and CapabilityInputSchema."
```

### Create the worker CLI

```
opencode run --agent primary "Create the CLI package cli/ with:
- cli/commands/caps.py: write, validate, show
- cli/commands/tasks.py: submit, list, watch
- cli/client.py: HTTP client (RelayClient)
- cli/commands/discover.py: capabilities, nodes

The CLI uses Typer. caps write does an atomic write (tmp → validate → mv).
task submit fetches capabilities from the server, validates the payload locally, sends the task."
```

---

## Build commands

```bash
# Full build (in the project directory)
pip install -e .

# Tests
pytest -x -q

# Ruff (linting)
ruff check .

# Test a single module
pytest tests/test_discovery.py -v
```

---

## Conventions

- **Python version:** 3.11+
- **Formatting:** Ruff (line-length 100, target py311)
- **Test framework:** pytest + pytest-asyncio
- **Docstrings:** Google style
- **Commits:** Conventional Commits (`feat:`, `fix:`, `refactor:`)
- **No** API keys or secrets in code/config – only `[REDACTED]`

---

## Task reference

See `TASKS.md` (in the project root) for the detailed task list.
| ID | Task | Prio | Status |
|----|---------|------|--------|
| T-010 | Input schema validation in capability.py | 🔴 | ⬜ todo |
| T-011 | Atomic write CLI (`caps write`) | 🔴 | ⬜ todo |
| T-012 | mtime check + SIGHUP reload | 🟡 | ⬜ todo |
| T-013 | Credential refresh in the worker | 🔴 | ⬜ todo |
| T-014 | Artifact download in the worker | 🟡 | ⬜ todo |
| T-015 | Discovery API endpoints | 🔴 | ⬜ todo |
| T-016 | POST /scheduler/task-simple | 🔴 | ⬜ todo |
| T-017 | Worker CLI task submit | 🟡 | ⬜ todo |
| T-018 | CLI capability cache | 🟢 | ⬜ todo |
| T-019 | Token management/auto-refresh | 🔴 | ⬜ todo |
| T-020 | Schema validation input constraints | 🟡 | ⬜ todo |