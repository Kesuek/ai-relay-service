# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- T-052: Task notes — nodes can leave free-form text notes on a task while it is being worked on (mini-chat between collaborating nodes). New table `task_notes`, new endpoint `POST /relay/v2/scheduler/tasks/{task_id}/notes` (body `{"message": "..."}`, 1..2000 chars), `GET /relay/v2/scheduler/tasks/{task_id}` now includes a `notes` array ordered by `created_at`. New CLI subcommand `node-cli task note <task_id> <message>` and `node-cli task wait` streams new notes live as they arrive.
- T-053: Capability details on claim and task-view — `POST /relay/v2/scheduler/claim` and `GET /relay/v2/scheduler/tasks/{task_id}` now include `capability_details` (description, type, input_schema) on each stage, resolved from the node's heartbeat-advertised metadata. The `node-cli` daemon now forwards `description`, `type` and `input_schema` from the YAML profile in every heartbeat; `node-cli claim`, `task result` and `task wait` print the resolved metadata.
- T-048: Capability-eigene Dashboard-Seiten — `dashboard_page`-Feld im Capability-YAML-Profil, `node-cli artifact upload --capability <name>` lädt die HTML-Seite auf den Server hoch (Speicher unter `~/.relay/capability-pages/<name>/dashboard.html`, kein Artifact-DB-Eintrag), `GET /relay/v2/capabilities/<name>/dashboard-page` servt die Seite, Dashboard-Tab "Capabilities" zeigt klickbare Karten und bettet die Seite in einem same-origin iFrame ein.
- `owner_node_id` routing — tasks with `owner_node_id` set can only be claimed by that specific node. `Scheduler.claim_stage()` skips stages whose task owner does not match the claiming node. (T-046)
- `node-cli task submit --owner <node_id>` — new flag pins a task to a specific node by setting `owner_node_id` in the request body. The field is omitted from the body when the flag is not used. (T-046)
- `node-cli capabilities server` — new subcommand to query all capabilities registered on the relay server (across all nodes), including node names. `RelayClient._get()` added for GET requests. (T-035)
- Cross-platform load normalisation: `(load_avg / cpu_count) * 100` — load is now reported as a percentage (0–100%) instead of raw load average, making it comparable across Linux, macOS, and Windows. `load_cap` default is now `cpu_count * 100` (dynamically calculated). (T-037)

### Changed

- `src/relay_server/api/v2/scheduler.py` — `POST /scheduler/tasks` and `POST /scheduler/task-simple` no longer default `owner_node_id` to the submitting node's ID. `owner_node_id` is now opt-in (only set when the client explicitly provides it). Tasks without an owner remain claimable by any matching node. (T-046)
- `src/relay_server/models/__init__.py` — `HeartbeatRequest.load` and `NodeHeartbeatRequest.load` validation range changed from `[0.0, 1.0]` to `[0.0, 100.0]` to match the new percentage-based load reporting.
- `nodes/common/poller.py` — `load_cap` removed from `DEFAULT_CONFIG` (now calculated from `os.cpu_count()` at runtime).
- `docs/node/capabilities.md` — "Node types" section replaced with "Capability types" table (KI-capable `.ai` vs KI-less `.native`), clarifying that a single node can offer both types side by side.

### Removed

- `nodes/common/poller.py` — legacy Poller class removed. All utility functions (load_config, load_meta, load_token, save_token, etc.) extracted to `nodes/common/node_utils.py`. The node-cli daemon (`node_cli.py`) has fully replaced the old poller as the recommended worker implementation. (T-039)

### Added

- `nodes/common/node_utils.py` — shared utility functions extracted from the legacy poller. Used by `node_cli.py` and `RelayClient` for config/meta/token file I/O.
- `node-cli task result <id>` — query task status, stages, and linked artifacts.
- `node-cli task wait <id> [--interval N]` — poll until task completion, then show result. (T-040)

### Fixed

- `src/relay_server/core/discovery.py` — Capability-Availability-Bug: a node heartbeating with `available: false` no longer overrides the availability for all other nodes sharing the same capability. Now checks if any other node still has the capability available before setting it to false. (T-036)
- `nodes/common/node_cli.py` — Heartbeat body was missing `available: True`, causing the server to set the node to `available: false` on every heartbeat. (T-038)
- `src/relay_server/core/discovery.py` — `endpoint` field removed from `_node_row_to_dict()` to prevent leaking internal network addresses between nodes in the public discovery response. (T-048)

### Changed

- Complete `docs/` restructure: `docs/concepts.md` (central concept doc), `docs/server/` (setup, admin, dashboard), `docs/node/` (setup, cli-reference, capabilities, token-lifecycle), `docs/reference/` (api, design-board). Old files (`admin/`, `node-operator/`, `adr/`, `nodes-design.md`, `token-concept.md`, `design-board.md`, `dashboard.md`, `BUILDING.md`) removed.
- `README.md` — doc table updated with new structure, legacy name mapping table, Python 3.11+ requirement, linting/formatting commands.
- `STATUS.md` — Phase 6 completed with all T-001–T-033 tasks, test count updated to 203.
- `AGENT_README.md` — cross-links updated to new doc paths.
- All peripheral READMEs (`nodes/common/`, `nodes/storage-node/`, `examples/nodes/`, `examples/agent-integration/`) — cross-links updated.
- Docs serving layer (`src/relay_server/api/v2/docs.py`) — whitelist updated with new doc names and backward-compat aliases.
- Dashboard redirect (`/agent-readme`) and login.html link updated to new doc names.

### Deprecated

- `nodes/worker/worker.py` — removed. Superseded by `nodes/common/node_cli.py` which provides daemon control, capability management, artifact upload/download, and 15+ CLI commands. No code in the repository referenced `worker.py`.

### Fixed

- `nodes/common/capability_loader.py` — `description` field added to allowed keys and normalized keys (was silently rejected by YAML profile validation).
- `docs/server/admin.md` — clone URL corrected from `github.com/felix/` to `github.com/Kesuek/`.
- `docs/server/{setup,admin,dashboard}.md` and `CHANGELOG.md` — `relay-recovery` syntax corrected to include `--db-path ~/.relay/server.db`.
- `docs/node/token-lifecycle.md` — added missing `adm_` and `bs_` token types, added "Automatic token cleanup" section.
- `docs/concepts.md` — added token-cleanup watchdog note to security model.
- `docs/reference/api.md` — `worker-heartbeat` endpoint documented with payload and `replace_capabilities=True`.
- `docs/reference/design-board.md` — db-node capabilities corrected to use `.native` suffix.
- `docs/node/cli-reference.md` — env-var table corrected (`RELAY_RUNTIME_TOKEN` is not yet honoured by the CLI; server-only vars clearly marked).