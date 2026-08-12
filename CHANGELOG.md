# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] - 2026-08-12

### Added

- **Storage Node as a real service (T-127 / T-128 / T-129 / T-136)** — the
  storage node is a first-class service with real Python handlers replacing the
  shell stubs: `storage.store` (inline `data_base64` or `artifact_id` stream),
  `fetch`, `delete` (recursive), `list` (prefix), `quota`, `stat`, `move`.
  Shared `_safe_path` guard rejects path-traversal and symlink escapes.
  `node-cli route` subcommand manages temporary bridge routes (`register` /
  `unregister` / `list`).
- **Bridge upload/download channels (T-129)** — large files stream directly
  storage<->caller through a temporary bridge route instead of through the
  relay. The relay proxy streams request body and upstream response chunkwise
  (no RAM buffering — OOM fix). `upload_channel` / `download_channel` complete
  the task with `{upload_url/download_url, channel_id, ttl}`.
- **Backup management (T-130 / T-131 / T-132)** — versioned, identifiable
  backups with a JSON manifest per backup (no SQLite): `backup.create` /
  `list` / `info` / `restore` / `delete` / `retention`. Retention policies
  (`keep_last`, `max_age_days`, GFS) run as tasks; a retention watchdog applies
  them from `~/.relay/retention.yaml`.
- **Folder transfer as `.tar.gz` (T-133 / T-134 / T-135)** — `storage.store`
  with `action: "extract" | "store_as_is"`, plus standalone `storage.extract`
  and `storage.archive`. Extracting rejects path-traversal entries and symlinks.
- **Docker base + special-node catalog (T-119 / T-120 / T-121 / T-122)** — a
  reusable base image (`docker/nodes/base/`) carries the node stack; each
  service (`docker/nodes/storage/`) is a thin `FROM ai-relay-node-base` layer
  with `node.yaml` + `handlers/`. Legacy `nodes/storage-node/` removed.
- **Temporary bridge routes with TTL (T-123 / T-124 / T-125 / T-126)** — routes
  with `expires_at` + `channel_id`, task-driven creation, TTL cleanup watchdog.
  `RelayClient.register_temp_route()` / `unregister_temp_route()`.
- **GPU-aware auto-busy (T-113)** — nodes are marked `busy` not only on
  sustained CPU load but also when `queue_depth >= 1` (a task already in
  flight). A node saturating its GPU while CPU stays idle is immediately busy.
- **Extended observability metrics (T-115)** — latency histograms
  (`relay_stage_duration_seconds`, `relay_claim_duration_seconds`,
  `relay_task_duration_seconds`), retry rate, per-node gauges
  (`relay_node_load`, `relay_node_queue_depth`, `relay_node_online`),
  throughput (`relay_tasks_created_5m`, `relay_tasks_completed_5m`). The
  built-in dashboard adds latency p50 cards, a retry-rate bar and a per-node
  load list.
- **Native TLS (T-111)** — the relay serves HTTPS directly (uvicorn-bound
  cert). mDNS is suppressed when TLS is active. Node clients support an
  optional `tls_ca_cert` for private/self-signed CAs.
- **PostgreSQL backend via SQLAlchemy Core (T-110)** — the database layer is
  decoupled from the SQLite dialect. All schema + query code goes through
  SQLAlchemy Core; switching to Postgres is a config change. `PostgresDatabase`
  with connection pool; `?` placeholders rewritten per dialect. The existing
  SQLite DB stays byte-identical (hard backcompat gate).
- **Server-Side Node (SSN)** — capability-page + proxy SSN implementation;
  dashboard-driven capability pages served through the relay.
- **Federation Node concept** — a node that heartbeats `federation`, connects
  to remote relays and forwards tasks; dashboard-controlled capability sharing.

### Changed

- **Node directory structure renamed (T-148)** — `docker/base/` →
  `docker/nodes/base/`, `docker/storage/` → `docker/nodes/storage/`. Consistent:
  `docker/server/` (relay) + `docker/nodes/` (node images).
- **Node default name** — the storage image ships `NODE_NAME=storage-node` so
  the node shows up in the dashboard under a readable name instead of the
  container hostname.
- **Bridge allowlist mDNS fallback (T-152)** — the bridge source-IP allowlist
  resolves the relay IP from `RELAY_URL`, or falls back to mDNS discovery when
  `RELAY_URL` is unset, so an mDNS-only deployment works without an explicit
  `RELAY_SERVER_IP`.
- **Long-run profile publishing (T-163)** — the capability profile ships in
  the image (`/app/profiles/`) and is copied to `~/.relay/node.yaml` on every
  start, so image updates ship a fresh capability set instead of reusing a
  stale persistent-volume copy.
- **Long-run handler budget (T-163)** — `long_run: true` capabilities get a
  2-hour budget instead of the 300s default; the daemon sends a `longrun` note
  that moves the stage to `accepted`, and progress notes reset the TTL (T-160).
- **Centralized status system (T-078…T-085)** — a status registry with
  categories + transitions for tasks, stages, nodes, users. `status_changed`
  SSE events, `node-cli node busy/idle/status/clear-status`.
- **Capability availability bug fixed (T-036 / T-038)** — a node heartbeating
  `available: false` no longer overrides availability for other nodes sharing
  the capability; heartbeat now carries `available: True`.
- **Cross-platform load normalisation (T-037)** — load reported as a percentage
  (`(load_avg / cpu_count) * 100`) instead of a raw load average.

### Fixed

- **Offline node token recovery (T-137)** — an offline node with a valid fresh
  registration secret can recover its runtime token; `pending` (not yet
  approved) nodes stay blocked.
- **`node-cli update apply` service target (T-137a)** — restarts
  `ai-relay-node-daemon.service` (the active SSE worker) instead of the
  disabled polling daemon.
- **Daemon auth-loop self-healing (T-108)** — a daemon stuck in a
  `Heartbeat 401 → Refresh 401 → Recovery 404` loop now self-heals: re-reads
  the token file on refresh+recovery failure, exponential backoff
  (10s→…→300s) on consecutive 401/403s, and a `auth_loop=true` degraded status.
- **Claim-retry protection (T-060)** — stages are finally marked `failed` after
  `max_retries` instead of being reset to `pending` forever; handler contract
  tightened (exit != 0 on error, valid JSON only on stdout).
- **Offline detection for claimed stages (T-061)** — `mark_offline_nodes()`
  fails all claimed stages of an offline node immediately.
- **Relay startup crash (T-028)** — missing `RELAY_SESSION_SECRET` no longer
  crashes the server shortly after boot (fail-fast with a clear message).

### Removed

- `nodes/worker/worker.py` — superseded by `nodes/common/node_cli.py`.
- Legacy `nodes/storage-node/` (storage_node.py, poller, Dockerfile, compose).
- Build artifacts, `__pycache__/`, and `.hermes/` working files from tracking.

### Deprecated

- The legacy `nodes/common/poller.py` Poller class — replaced by the
  `node-cli` daemon. Utility functions moved to `nodes/common/node_utils.py`.

[Unreleased]: https://github.com/Kesuek/ai-relay-service/compare/v2.0.0...HEAD
[2.0.0]: https://github.com/Kesuek/ai-relay-service/releases/tag/v2.0.0
