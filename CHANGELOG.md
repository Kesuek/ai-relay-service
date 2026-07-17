# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `node-cli capabilities server` — new subcommand to query all capabilities registered on the relay server (across all nodes), including node names. `RelayClient._get()` added for GET requests. (T-035)
- Cross-platform load normalisation: `(load_avg / cpu_count) * 100` — load is now reported as a percentage (0–100%) instead of raw load average, making it comparable across Linux, macOS, and Windows. `load_cap` default is now `cpu_count * 100` (dynamically calculated). (T-037)

### Changed

- `src/relay_server/models/__init__.py` — `HeartbeatRequest.load` and `NodeHeartbeatRequest.load` validation range changed from `[0.0, 1.0]` to `[0.0, 100.0]` to match the new percentage-based load reporting.
- `nodes/common/poller.py` — `load_cap` removed from `DEFAULT_CONFIG` (now calculated from `os.cpu_count()` at runtime).

### Fixed

- `src/relay_server/core/discovery.py` — Capability-Availability-Bug: a node heartbeating with `available: false` no longer overrides the availability for all other nodes sharing the same capability. Now checks if any other node still has the capability available before setting it to false. (T-036)
- `nodes/common/node_cli.py` — Heartbeat body was missing `available: True`, causing the server to set the node to `available: false` on every heartbeat. (T-038)

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