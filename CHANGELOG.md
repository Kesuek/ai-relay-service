# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `docs/getting-started.md` — quick-start guide with 3 scenarios (run a node, relay + node, multi-node cluster) and a decision tree.
- `docs/reference/api.md` — "Worked examples (cURL)" section with 10 endpoint examples, error-code table, and rate-limit documentation.
- `docs/concepts.md` — Glossary (20 terms), KI/AI terminology clarification, explicit `.native` suffix rule for all KI-less nodes.
- `docs/server/setup.md` — HTTPS/TLS section (reverse proxy with Caddy), database persistence & backup, full config-parameter reference table, session-secret rotation guide, performance & scaling notes.
- `docs/node/capabilities.md` — Handler contract table (exit codes, timeout, SIGKILL, stdout/stderr handling).
- `docs/node/setup.md` — Token storage alternatives (bind-mount, secret manager), expanded troubleshooting (network, permissions, Python version, systemd, daemon startup).
- `docs/server/admin.md` — Expanded recovery workflow (what `--all` does, how to disable recovery).
- `docs/setup.md` and `docs/node-readme.md` — replaced bare redirects with decision-tree templates.

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