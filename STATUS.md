# AI-Relay-Service — Project Status

## Overview

| Field | Value |
|-------|-------|
| **Version** | 2.0.0 |
| **Port** | 8788 |
| **Framework** | FastAPI + SQLite (WAL, SQLAlchemy Core) |
| **Owner** | Ronny Pietschke |
| **Tests** | 512/512 passed (T-127–T-129 + T-136 +69, backcompat invariant intact) |
| **Last Commits** | ed50b3e → e33a982 → f4aec86 → 4b624d2 → 2222f4b → 7ba5aaf → 1fcf787 → 6a9c83e → 09d0a8c → 122dca6 → c96d71e → f4827c4 → bc70188 → 85a7971 |

## Phase Status

### Phase 1 — Core Infrastructure ✅
- [x] SQLite schema (nodes, tasks, task_stages, artifacts, users, groups, permissions, admin_seeds)
- [x] Additive DB migration system (no-downtime ALTER TABLE)
- [x] Config via `config.yaml` + `RELAY_*` env override
- [x] Node registry with collision-free ID minting (ADR-001, 8-char base32)

### Phase 2 — Auth & Security ✅
- [x] bcrypt (12 rounds) with legacy SHA-256 migration
- [x] 4 token types: admin seed (`adm_`), bootstrap (`bs_`), temporary (`tp_`), runtime (`rt_`)
- [x] Token rotation — single valid runtime token per node
- [x] Registration secret recovery (7d TTL, matches token TTL)
- [x] RBAC: users, groups, permissions, roles (superadmin / admin / user)
- [x] CSRF protection (double-submit cookie)
- [x] Rate limiting on dashboard (SlowAPI)
- [x] Security headers (X-Content-Type-Options, X-Frame-Options, CSP, Referrer-Policy, Permissions-Policy)
- [x] Force password change on first login
- [x] Common password blocklist (20 entries)

### Phase 3 — Task Lifecycle ✅
- [x] Multi-stage DAG tasks
- [x] `POST /scheduler/tasks` — create with stages
- [x] `POST /scheduler/claim` — claim next pending stage
- [x] `POST /scheduler/stages/{id}/complete` — complete with result
- [x] Priority queue (0–10)
- [x] Configurable timeout per task
- [x] Auto-complete remaining stages on final completion

### Phase 4 — Monitoring & Events ✅
- [x] SSE event stream (`/events/stream?node=&types=`)
- [x] Event types: node_online, node_offline, task_created, stage_claimed, stage_completed, presence_changed, artifact_created
- [x] In-memory EventBus (500 history, backpressure-safe)
- [x] Presence system (status, mood, activity, progress, ETA)
- [x] Dashboard with live SSE, RBAC, node approval
- [x] Discovery query with 5 simultaneous filters

### Phase 5 — Nodes & Integration ✅
- [x] Generic Worker Node — heartbeat 8s, SIGHUP reload, mtime-check, exponential backoff (5 retries, max 60s), graceful shutdown
- [x] Storage Node — archive, delete, list, quota with auto-cleanup task posting
- [x] Generic Agent Poller — JSON-configurable, credential refresh, 401/403 auto-recovery

### Phase 6 — Hardening & Cleanup ✅
- [x] Artifact upload/download from worker side (T-001)
- [x] Worker-seitiger Token-Refresh (T-002)
- [x] YAML schema validation for capabilities.yaml (T-003)
- [x] Node README improvement feedback reviewed
- [x] SQLite Lock Contention (T-016)
- [x] Task Timeout enforced (T-017)
- [x] Poller Hard Exit (T-018)
- [x] Inconsistent Logging Levels (T-019)
- [x] Dashboard CSRF Policy dokumentiert (T-020)
- [x] Missing Type Hints (T-021)
- [x] Secrets in Logs vermeiden (T-024)
- [x] Dashboard-Token TTL verkürzen (T-025)
- [x] Capabilities normalisieren (T-026)
- [x] validate_token synchroner DELETE → Token-Cleanup-Watchdog (T-027)
- [x] CRITICAL: Relay stürzt nach ~20s ab — RELAY_SESSION_SECRET fehlte (T-028)
- [x] LOW: Bootstrap-Seite Copy-Button + Login-Link (T-029)
- [x] Dokumentation: Server + Node-CLI + Node-Setup überarbeitet (T-030)
- [x] Dokumentation: Komplette Restrukturierung (T-031)
- [x] GitHub Review Findings behoben (T-032) — 11 Findings
- [x] Zweiter GitHub-Review behoben (T-033) — 22 Findings
- [x] `description`-Field in capability_loader ergänzt

### Phase 7 — CLI-Erweiterungen & Bugfixes ✅
- [x] `node-cli capabilities server` — Server-Capability-Query (T-035)
- [x] Capability-Availability-Bug in `get_capabilities()` gefixt (T-036)
- [x] Cross-platform load normalisation: `(load_avg / cpu_count) * 100` (T-037)

### Phase 8 — Routing & Adressierung ✅
- [x] `owner_node_id` in `claim_stage()` respektieren — Tasks lassen sich an einen bestimmten Node pinnen (T-046)
- [x] `node-cli task submit --owner <node_id>` — Owner-Flag im Client (T-046)

### Phase 18 — Zentrales Status-System ✅
- [x] T-078: `core/status.py` — zentrale Status-Registry (Kategorien AVAILABLE/BUSY/PENDING/TERMINAL/OFFLINE, Lookup-Helper, Transitions-Prüfung, Farb-Mapping)
- [x] T-079: DB-Migration — `users.status` + `nodes.consecutive_high_load` Spalten
- [x] T-080: Scheduler-Umbau auf Kategorie-Logik (`node_can_claim`, `node_claim_statuses`, `mark_offline_nodes` für AVAILABLE+BUSY)
- [x] T-081: Heartbeat `status` + `load_cap` Felder, Auto-Busy bei anhaltend hoher Last, `auto_busy_consecutive_heartbeats` Config
- [x] T-082: `status_changed` SSE-Event an allen Node/Task/Stage-Übergängen
- [x] T-083: Dashboard-Rendering — `status_category` + `status_color` im Overview-Response, `statusColor()` in dashboard.js
- [x] T-084: `node-cli node busy`/`idle`/`status`/`clear-status` Subcommands
- [x] T-085: User-Status vorbereitet (`users.status`, `USER_STATUSES`-Registry)
- [x] T-086: Doku — concepts.md (Status System Abschnitt), cli-reference.md, api.md, CHANGELOG, STATUS

### Phase 19 — Node-Konfiguration umbenennen ✅
- [x] T-087: `capability_loader.py` → `node_config.py`, `capabilities.active.yaml` → `node.yaml`, `capabilities.active.profile` → `node.profile`, `capabilities.d/` → `profiles.d/`; Schema gelockert (`capabilities` optional, `additionalProperties` auf Root, `node_name`/`description` Top-Level-Properties); `write_active_status()` regex-basiert; Migration beim ersten Start (`_migrate_old_paths()`); Doku + Tests + CLI-Referenzen aktualisiert

### Phase 25 — Observability ✅
- [x] T-109: Observability — Metrics + eingebautes Dashboard + strukturierte Logs
  - `core/metrics.py` — Registry (In-Process-Counter), DB-Gauges (Tasks/Stages/Nodes/Queue), `render_prometheus()`
  - `/metrics` (offen, Prometheus-Text) + `/ready` (DB/Scheduler/Event-Bus) in `main.py`
  - Auth-Failure-Counter via Middleware (401/403/429 → `relay_auth_failures_total{endpoint="..."}`)
  - `/relay/v2/dashboard/api/metrics` (JSON, Session-Auth) + `/relay/v2/dashboard/metrics` (HTML, CSP-konform, externes `metrics.js`)
  - Strukturierte JSON-Logs via `core/logging_setup.py`, per-Request `trace_id` (16-hex) via `contextvars` + `X-Relay-Trace-Id`-Header

### Phase 26 — PostgreSQL-Backend (SQLAlchemy Core) ✅
- [x] T-110: Database layer decoupled from the SQLite dialect
  - `core/tables.py` — 17 tables as portable `sa.Table` objects; `metadata.create_all` works on any backend
  - `SqliteDatabase` backed by a SQLAlchemy engine (lazy, reads `settings.db_path` live); existing on-disk SQLite DB stays byte-identical (hard gate, `tests/test_db_backcompat.py`)
  - `PostgresDatabase` implemented — engine + `pool_pre_ping` pool, activated via `db_type: postgres` + `pg_dsn` + `pip install ".[postgres]"`
  - `q(sql, params)` helper rewrites `?` placeholders to named bind params so SQLAlchemy renders per dialect; 155 query call sites ported
  - `Row["col"]` / `Row.keys()` compat shim keeps the 373+ legacy row-access sites unchanged
  - Migrations backend-aware: `PRAGMA table_info` (SQLite) vs `information_schema.columns` (Postgres), centralised in `_column_names()` / `_table_names()`
  - `maintenance.db_vacuum` backend-aware (SQLite WAL checkpoint + VACUUM; Postgres autovacuum)
  - Timestamps remain ISO-8601 TEXT (no on-disk format change); TIMESTAMPTZ migration is a later, separate step

### Phase 27 — Node-Client-Härtungen + Refactor ✅
- [x] T-111: Native TLS (tls_certfile/tls_keyfile), mDNS suppression, node `tls_ca_cert`
- [x] T-112: Shared `RelayClient` extracted into `nodes/common/relay_client.py`
- [x] T-113: GPU-aware auto-busy via `queue_depth >= 1`
- [x] T-114: Deterministic session-secret fixture (cross-module test isolation)
- [x] T-115: Observability metrics — latency histograms, retry rate, per-node gauges, throughput
- [x] T-116: Relay server Docker image + compose (SQLite/PostgreSQL backend choice)
- [x] T-117: node-cli split into `cli/cli_*` submodules, `_read_pid`/`_pid_running` → `node_utils`
- [x] T-118: Centralized proactive token refresh in `RelayClient.maybe_refresh_token`
- [x] T-137: Offline-Node mit gültigem frischem Registration-Secret kann Runtime-Token recoveren (Recovery-Gate blockiert nur noch `pending`)
- [x] T-137a: `node-cli update apply` startet den aktiven `node-daemon`-Service (SERVICE_UNIT default)

### Phase 28 — Docker-Basis + Spezial-Node-Katalog (Plan A) ✅
- [x] T-119: Node base image `docker/base/` — installs the node stack from the project wheel; entrypoint translates `RELAY_URL`/`NODE_NAME`/`NODE_PROFILE` into `relay_config.json`+`node.yaml`, registers the node on first start, execs `node-daemon`; healthcheck reads the daemon status file
- [x] T-120: Storage service image `docker/storage/` — `FROM ai-relay-node-base`, layers `node.yaml` + stub handlers (return `{"error": "not implemented yet"}`); real handlers land in Plan B (Phase 30)
- [x] T-121: Legacy `nodes/storage-node/` removed (storage_node.py, register.py, Dockerfile, compose, service unit, build-bundle/deploy scripts); `_safe_path` logic preserved as reference in `docker/storage/handlers/REFERENCE_safe_path.md` for Plan B
- [x] T-122: `docker/README.md` — special-node catalog: base image + service-image pattern, env reference, "how to add a new service" walkthrough, storage example

### Phase 29 — Temporäre Bridge-Routen (TTL-basiert) ✅
- [x] T-123: `node_routes` extended with `expires_at` + `channel_id`; `_lookup_route()` treats expired temp routes as 404; additive migration for existing SQLite DBs; `proxy_node_route` no longer proxies DELETE (reserved for unregister)
- [x] T-124: `POST /api/node-routes/register` (Bearer node-token auth, TTL + channel_id validation, UPSERT) + `DELETE /api/node-routes/{node_id}/{path}` (owner-only); bridge routes get `auth = "node_token"`
- [x] T-125: `temp_route_cleanup` watchdog reaps expired temp routes (`expires_at < now AND channel_id IS NOT NULL`); permanent heartbeat routes (`expires_at IS NULL`) untouched; interval configurable via `temp_route_cleanup_interval_seconds` (default 300s)
- [x] T-126: `RelayClient.register_temp_route()` + `unregister_temp_route()` — node-side helpers for T-124 endpoints; `unregister` swallows 404 (already expired/reaped)

### Phase 30 — Storage-Node Core + Bridge-Handler + Streaming-Fix + node-cli route (Plan B) ✅
- [x] T-136: `node-cli route register`/`unregister`/`list` subcommand (`--json` support); server `GET /api/node-routes` (Bearer node-token) lists the caller's own routes; `RelayClient.list_temp_routes()` helper
- [x] T-127: Real Python storage handlers replace shell stubs — `store` (data_base64 inline OR artifact_id stream), `fetch`, `delete` (recursive), `list` (prefix), `quota` (disk_usage + threshold), `stat`, `move`; shared `_common.py` with `_safe_path` (path-traversal + symlink-escape guard, ported from legacy storage_node.py); `node.yaml` handler paths switched to `.py`, all `.sh` stubs removed
- [x] T-128: `docker/storage/bridge_server.py` — Starlette server on `0.0.0.0:8791` serving `POST /upload/{channel_id}` + `GET /download/{channel_id}`; Source-IP-Allowlist middleware (server IP from RELAY_URL DNS, `RELAY_SERVER_IP` override); non-matching → 403, fail-closed when unresolved; streaming chunkwise; storage Dockerfile launches it alongside node-daemon
- [x] T-129: `upload_channel`/`download_channel` claimable tasks register a temp bridge route + complete with the public URL; relay proxy in `route_registry.py` streams request body (`request.stream()`) AND upstream response (`client.send(stream=True)` + `StreamingResponse`) chunkwise — OOM fix for large files; `_forward_headers` keeps `content-length` for streaming

### Phase 31 — Backup-Management (T-130/T-131/T-132) ✅
- [x] T-130: Backup-Metadaten-Modell — JSON-Manifest pro Backup (kein SQLite, DECISIONS 2026-08-06) unter `<STORAGE_PATH>/backups/<backup_id>/manifest.json` neben `data.bin`; Felder `backup_id`/`source`/`type`/`base_backup_id`/`created_at`/`size_bytes`/`retention`/`status`; geteilte Helfer in `docker/storage/handlers/backup_common.py` (atomares Manifest-Schreiben, Backup-ID-Minting, Traversal-Schutz)
- [x] T-131: Backup-Handler — `backup.create` (inline `data_base64` ODER `artifact_id`-Stream; `incremental` verlangt existierende `base_backup_id`), `backup.list` (Filter `source`/`type`, schließt `deleted` aus), `backup.info`, `backup.restore` (inline ≤10 MB, größere als `download_url: null`-Platzhalter), `backup.delete` (markiert `deleted`, Manifest bleibt als Audit)
- [x] T-132: Retention — `backup.retention {source, policy}` als Task (`keep_last`/`max_age_days`/GFS `keep_daily`/`keep_weekly`/`keep_monthly`); `docker/storage/retention_watchdog.py` periodischer Background-Loop, Policies aus `~/.relay/retention.yaml` (`RELAY_RETENTION_CONFIG`), Intervall `RELAY_RETENTION_INTERVAL` (Default 3600s), gestartet vom Storage-Entrypoint; leere Config = kein Auto-Delete (fail-safe)
- [x] Alle `backup.*`-Capabilities in `docker/storage/node.yaml` deklariert; 19 neue Tests in `tests/nodes/test_backup_handlers.py`; Doku in `docs/node/storage.md` (Manifest-Schema, Handler-Referenz, Retention-Watchdog)

### Phase 32 — Ordner-Übertragung + Doku (T-133/T-135/T-134) ✅
- [x] T-133: `storage.store` mit `action: "extract" | "store_as_is"` (Default `store_as_is`) — `extract` entpackt die tar.gz in ein Verzeichnis, `store_as_is` legt sie unangetastet ab; Traversal-Einträge + Symlinks im Archiv werden abgelehnt; funktioniert für `data_base64`-Inline UND `artifact_id`-Stream
- [x] T-135: `storage.extract {path}` (entpackt abgelegte tar.gz in Verzeichnis, Archivname minus Suffix) + `storage.archive {path, target}` (packt Ordner in tar.gz); beide mit Traversal-Schutz
- [x] T-134: Doku — `docs/node/storage.md` um Ordner-Übertragung erweitert (action-Flag, extract/archive-Referenz, typischer Flow); CHANGELOG + STATUS aktualisiert
- [x] `storage.extract`/`storage.archive`-Capabilities in `node.yaml` deklariert; 9 neue Tests in `tests/nodes/test_storage_handlers.py`

---

## Code Review Summary (historical — all findings resolved)

> The F1–F6 findings below are historical. All of them have been addressed in
> later commits; this table is kept only for traceability.

| # | File | Severity | Finding | Resolution |
|---|------|----------|---------|------------|
| F1 | `discovery.py:98` | Medium | `config_filter` JSON parse with no try/except | ✅ Fixed |
| F2 | `poller.py:211` | Low | `fromisoformat()` fails on `Z`-suffix pre-3.11 | ✅ Fixed |
| F3 | `scheduler.py:205` | Info | `claim_stage` matches only `pending` | ✅ Correct per spec |
| F4 | `models/capability.py` + `common/capability.py` | Medium | Duplicate `CapabilityInputSchema` | ✅ Consolidated |
| F5 | `worker.py` vs `poller.py` | Low | Task-timeout inconsistent | ✅ Centralized via config |
| F6 | All docs | Task | German docs need English translation | ✅ Done |

**Security Audit: PASS** — bcrypt migration, timing-safe compare, CSRF, CORS, rate-limiting, input validation all verified. No critical findings.

## Architecture

```
┌──────────────────────────────────────────────┐
│  API v2 Router                               │
│  /auth · /discovery · /scheduler · /storage  │
│  /presence · /events · /dashboard · /admin   │
├──────────────────────────────────────────────┤
│  Core Services                               │
│  auth · discovery · scheduler · artifacts    │
│  · presence · events · session · users · db  │
├──────────────────────────────────────────────┤
│  SQLAlchemy Core (portable schema + queries) │
│  SQLite (default) · PostgreSQL (opt-in)      │
│  nodes · tasks · stages · artifacts          │
│  · users · groups · permissions · seeds      │
├──────────────────────────────────────────────┤
│  Node Clients                                │
│  node-cli · node-daemon · docker/base +      │
│  docker/storage (service images)             │
└──────────────────────────────────────────────┘
```