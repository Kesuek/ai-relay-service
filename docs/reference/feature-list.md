# Feature List

Complete, structured catalogue of every feature in the AI-Relay-Service,
grouped into 22 categories with ~210 features. Each entry has a short
description and a file/line reference to its primary implementation site.

> The references point to the *primary* implementation site (function or class
> definition, or core logic). Many features span several modules — for example
> auth logic lives in `core/auth.py` + the API in `api/v2/auth.py` + security
> deps in `api/v2/security.py` + models in `models/__init__.py`. The
> `.hermes/plans/` folders contain a planning document for most features
> (numbered T-050, T-060, T-069, T-075, …) and act as a quasi feature tracker.

For the concepts behind these features see [../concepts.md](../concepts.md).
For endpoint details see [api.md](api.md).

---

## 1. Server Core / Infrastructure

| Feature | Description | Implementation |
|---|---|---|
| **FastAPI app with lifespan** | App init, DB init, maintenance loop, mDNS start, SSN start on startup; cleanup on shutdown | `src/relay_server/main.py:54-106` (`lifespan`) |
| **Security-headers middleware** | Sets CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy on all responses | `src/relay_server/main.py:27-42, 209-218` |
| **Node-routes CSP exception** | Looser CSP (inline scripts, frame-ancestors 'self') for dynamic-node-route path so the dashboard can embed iframes | `src/relay_server/main.py:196-218` |
| **Force-password-change middleware** | Blocks dashboard usage until a user with `force_password_change` changes their password | `src/relay_server/main.py:221-248` |
| **Health endpoint** | `/health` returns status, version and event-subscriber count | `src/relay_server/main.py:278-285` |
| **Dashboard redirects** | `/dashboard` and `/dashboard/login` redirect depending on session state | `src/relay_server/main.py:254-275` |
| **Rate limiting** | slowapi IP-based limiter for auth and dashboard routes (e.g. 5/min login) | `src/relay_server/main.py:51, 174-180`; `api/v2/auth.py:34, 65, 106, 137, 277` |
| **V2 router aggregation** | Bundles all sub-routers under `/relay/v2` (docs, auth, admin, discovery, scheduler, presence, events, dashboard, storage) | `src/relay_server/api/v2/__init__.py:15-24` |
| **SQLite with WAL** | Connection factory with WAL mode, foreign keys, row factory | `src/relay_server/core/db.py:93-101` |
| **DB schema init** | Creates all tables (admin_seeds, node_seeds, node_tokens, users, groups, RBAC, nodes, node_capabilities, node_routes, presence, tasks, task_stages, artifacts, task_notes, audit_logs) + indices | `src/relay_server/core/db.py:130-405` |
| **Schema migrations** | Lightweight `ALTER TABLE` migrations for new columns (force_password_change, registration_secret, description, token_lookup_hash, retry_count, capability fields) | `src/relay_server/core/db.py:408-502` |
| **Capability-index backfill** | Migrates `node_capabilities` from the old JSON column | `src/relay_server/core/db.py:505-565` |
| **SQLite lock retry** | `retry_on_locked` decorator with exponential backoff for DB writes | `src/relay_server/core/db.py:61-90`; `core/scheduler.py:20-43` |
| **Audit log with secret redaction** | Writes admin actions to `audit_logs`, redacts token/Bearer/password patterns before persistence | `src/relay_server/core/db.py:26-54, 651-684` |

## 2. Auth & Security

| Feature | Description | Implementation |
|---|---|---|
| **Master-admin seed** | One-time generated `adm_` seed for bootstrap/recovery; bcrypt hashed | `src/relay_server/core/auth.py:23, 177-197` |
| **Node registration (pending)** | Worker registers as `pending`, gets a temporary token + registration secret | `src/relay_server/core/auth.py:316-384`; `api/v2/auth.py:64-102` |
| **Admin-node registration** | Admin node via bootstrap secret, directly `approved` (only when no human admin exists) | `src/relay_server/core/auth.py:253-313`; `api/v2/auth.py:105-133` |
| **Node-ID minting (ADR-001)** | Cluster generates 8-char IDs from an unambiguous alphabet; never the client | `src/relay_server/core/node_registry.py:18-92` |
| **Token types** | `rt_` (runtime), `tp_` (temporary), `adm_` (admin seed), `bs_` (bootstrap), `rs_` (registration secret), `sec_` (generic) | `src/relay_server/core/auth.py:23-26, 55-58` |
| **bcrypt hashing** | All secrets/tokens with bcrypt (12 rounds); legacy SHA-256 still verified | `src/relay_server/core/auth.py:83-165` |
| **Deterministic token lookup** | HMAC-SHA256 pepper lookup replaces O(N) bcrypt scan; indexed in `token_lookup_hash` | `src/relay_server/core/auth.py:97-125, 453-511` |
| **Token validation** | Validates token against DB, status gate (approved/online), pending handling | `src/relay_server/core/auth.py:453-511` |
| **Token refresh** | Rotates runtime token (invalidates old); rotation of registration secret | `src/relay_server/core/auth.py:514-567`; `api/v2/auth.py:136-273` |
| **Token recovery via RS** | Recovery path: mint a new runtime token from the registration secret | `src/relay_server/core/auth.py:514-524`; `api/v2/auth.py:212-266` |
| **Registration-status poll** | Worker polls lifetime of RT and RS (pending or authenticated) | `src/relay_server/api/v2/auth.py:276-380` |
| **Node approval** | Admin approves pending node, deletes temporary tokens, issues runtime token | `src/relay_server/core/auth.py:387-451`; `api/v2/admin.py:47-74` |
| **Master-seed dashboard login** | Dashboard login via seed, only when no human admin or recovery mode active; short 1 h session | `src/relay_server/core/auth.py:605-648`; `api/v2/dashboard.py:181-241`; `core/session.py:18, 32-66` |
| **Human-user management** | Create/list/delete users, enable/disable, assign groups | `src/relay_server/core/users.py:89-400`; `api/v2/dashboard.py:645-750` |
| **Password policy** | At least 12 chars, common-password block list, force_password_change on creation | `src/relay_server/core/users.py:34-62, 89-143, 348-380` |
| **Password change (self)** | User authenticates with old password, then sets a new one, refreshes cookie | `src/relay_server/core/users.py:363-380`; `api/v2/dashboard.py:694-709` |
| **RBAC (groups/permissions)** | Default groups admin/user/viewer + 11 default permissions; group-permission assignment | `src/relay_server/core/db.py:568-648`; `core/users.py:182-345`; `api/v2/dashboard.py:753-785` |
| **Permission checks** | `check_dashboard_permission`, `has_permission`, `has_any_permission` | `src/relay_server/core/users.py:182-216`; `api/v2/security.py:198-213` |
| **Signed session cookies** | itsdangerous URLSafeTimedSerializer, HttpOnly, Secure, SameSite=Lax, per-token TTL | `src/relay_server/core/session.py:32-66` |
| **CSRF protection (double-submit)** | `relay_csrf` cookie + `X-CSRF-Token` header for mutating endpoints | `src/relay_server/core/session.py:69-79`; `api/v2/dashboard.py:132-141` |
| **Security dependencies** | `get_auth_context`, `get_approved_context`, `require_admin`, `require_dashboard_user`, `require_admin_or_dashboard_user` | `src/relay_server/api/v2/security.py:21-213` |
| **Admin-node token permissions** | Restricted permission whitelist for admin-node tokens without a human user | `src/relay_server/api/v2/security.py:191-213` |
| **Recovery CLI** | `enable-recovery` disables human admins to re-enable seed login | `src/relay_server/cli.py:48-91` |
| **Admin init-master-seed** | `relay admin init-master` generates the seed once | `src/relay_server/main.py:326-342` |

## 3. Config / Settings

| Feature | Description | Implementation |
|---|---|---|
| **Pydantic settings** | Env vars with `RELAY_` prefix, `.env` file | `src/relay_server/config.py:10-69` |
| **YAML config override** | `~/.relay/config.yaml` overrides env defaults, with path coercion | `src/relay_server/config.py:72-117` |
| **Configurable limits** | Token TTL, claim TTL, heartbeat intervals, upload limits, maintenance intervals, SSN settings | `src/relay_server/config.py:13-65` |

## 4. Scheduler & Tasks

| Feature | Description | Implementation |
|---|---|---|
| **Task creation (DAG)** | Task with stages, linear DAG default dependencies, priority, owner node, timeout | `src/relay_server/core/scheduler.py:74-149`; `api/v2/scheduler.py:30-50` |
| **Simple task (single stage)** | Shortcut: capability + payload → single-stage task, checks capability availability | `src/relay_server/api/v2/scheduler.py:188-244` |
| **Task listing / detail** | Filter tasks by status; task view with stages, artifacts, notes, capability_details | `src/relay_server/core/scheduler.py:151-226`; `api/v2/scheduler.py:53-69` |
| **Stage claiming** | Atomic claim with capability matching (via `node_capabilities` index), dependency check, owner-node enforcement | `src/relay_server/core/scheduler.py:228-374`; `api/v2/scheduler.py:90-99` |
| **Capability-type filter** | Claim can filter by capability type | `src/relay_server/core/scheduler.py:262-280` |
| **Stage completion** | Marks stage completed, task completed when all stages done, publishes events | `src/relay_server/core/scheduler.py:409-458`; `api/v2/scheduler.py:102-118` |
| **Task notes (mini-chat)** | Nodes leave free-text notes on tasks, visible to all participants | `src/relay_server/core/scheduler.py:376-407`; `api/v2/scheduler.py:72-87` |
| **Claim-TTL release & fail** | Expired claims → pending with retry_count, permanently failed after max_retries | `src/relay_server/core/scheduler.py:460-537` |
| **Stage-timeout enforcement** | Overdue claimed stages → `timed_out`, task too when all done | `src/relay_server/core/scheduler.py:539-614`; `api/v2/scheduler.py:168-174` |
| **Orphaned-stage fail** | Pending stages without a verifying node → failed (prevents eternal blocking) | `src/relay_server/core/scheduler.py:616-697` |
| **Owner-node deleted handling** | When owner node is deleted → stage becomes failed instead of forever pending | `src/relay_server/core/scheduler.py:314-332` |
| **Capability-details resolution** | Scheduler attaches `capability_details` (description, type, input_schema) to claim/task view | `src/relay_server/core/scheduler.py:182-192, 362-369`; `core/db.py:793-838` |
| **Payload size limit** | Pydantic validator rejects payload > `max_payload_bytes` | `src/relay_server/models/__init__.py:136-144, 311-318` |

## 5. Discovery & Nodes

| Feature | Description | Implementation |
|---|---|---|
| **Heartbeat** | Updates last_seen, load, queue_depth, available, endpoint, capabilities (merge or replace) | `src/relay_server/core/discovery.py:67-190`; `api/v2/discovery.py:20-39` |
| **Worker heartbeat (replace)** | `worker-heartbeat` replaces the full capability list | `src/relay_server/api/v2/discovery.py:42-62` |
| **Node-name/description override** | Heartbeat can set node_name and description (T-072) | `src/relay_server/core/discovery.py:118-124` |
| **Status transition** | offline → online, approved → online on first heartbeat; `node_online` event | `src/relay_server/core/discovery.py:144-188` |
| **Node listing** | List nodes, optionally filter by status (special word `all`) | `src/relay_server/core/discovery.py:193-217`; `api/v2/discovery.py:65-70` |
| **Node detail** | Single node by ID | `src/relay_server/core/discovery.py:220-232` |
| **Capability query by name** | Nodes for a capability (approved/online, filtered by last_seen) | `src/relay_server/core/discovery.py:235-259`; `api/v2/discovery.py:73-82` |
| **Capabilities listing (grouped)** | All capabilities with offering nodes, filter by type/available/config | `src/relay_server/core/discovery.py:262-421`; `api/v2/discovery.py:87-122` |
| **Capability detail** | Single capability with all nodes | `src/relay_server/core/discovery.py:424-429`; `api/v2/discovery.py:125-135` |
| **Normalized capability index** | `node_capabilities` table for efficient capability matching without JSON parse | `src/relay_server/core/db.py:240-261, 692-838` |
| **Sync node-capabilities** | Replace index rows on registration/heartbeat/approval | `src/relay_server/core/db.py:692-740` |
| **Offline detection** | Marks nodes offline on heartbeat timeout (TOCTOU-safe), fails their claims | `src/relay_server/core/discovery.py:432-537` |
| **Admin node listing** | Admin endpoint lists all nodes (excl. dashboard admin) | `src/relay_server/api/v2/admin.py:17-44` |
| **Admin issue token** | New runtime token for approved/offline node | `src/relay_server/api/v2/admin.py:77-123` |
| **Admin delete node** | Deletes node plus dependent records (tokens, presence, claims, artifacts) | `src/relay_server/api/v2/admin.py:126-176` |

## 6. SSE / Events

| Feature | Description | Implementation |
|---|---|---|
| **In-memory EventBus** | Async event bus with subscriber queues, drop-on-full for slow consumers | `src/relay_server/core/events.py:39-163` |
| **Event history** | Ringbuffer of the last 500 events for the `recent` endpoint | `src/relay_server/core/events.py:48-68` |
| **SSE stream** | `/events/stream` with `text/event-stream`, filterable by event types, node ID must match | `src/relay_server/api/v2/events.py:25-62` |
| **SSE formatting** | `event:`/`data:`/`X-Dropped:` header formatting | `src/relay_server/core/events.py:155-160` |
| **Subscriber-lag warning** | Publishes `subscriber_lagging` event on >100 drops | `src/relay_server/core/events.py:21-36` |
| **Publish from sync context** | `publish_sync` thread-safe via `call_soon_threadsafe` | `src/relay_server/core/events.py:120-133` |
| **Event types** | node_online, node_offline, task_created, stage_claimed, stage_completed, stage_failed, stage_timed_out, task_completed, task_failed, task_timed_out, presence_changed, artifact_created, artifact_deleted | scattered across `scheduler.py`, `discovery.py`, `presence.py`, `artifacts.py` |

## 7. Presence

| Feature | Description | Implementation |
|---|---|---|
| **Presence update** | Status, mood, activity, progress, ETA, next_available per node | `src/relay_server/core/presence.py:28-107`; `api/v2/presence.py:14-31` |
| **Presence listing** | List all presence records, optionally by status | `src/relay_server/core/presence.py:130-160`; `api/v2/presence.py:34-39` |
| **Presence detail** | Presence for a single node with node metadata | `src/relay_server/core/presence.py:110-128`; `api/v2/presence.py:42-49` |
| **Presence-changed event** | Event on change of any presence field | `src/relay_server/core/presence.py:101-104` |

## 8. Storage & Artifacts

| Feature | Description | Implementation |
|---|---|---|
| **Artifact storage (bytes)** | Stores bytes in `artifacts_dir` with SHA-256 checksum, sharded by ID prefix | `src/relay_server/core/artifacts.py:43-95` |
| **Artifact storage (streaming)** | `store_artifact_from_file` streams a file chunk-wise, no RAM load, SHA in one pass | `src/relay_server/core/artifacts.py:98-163` |
| **Artifact metadata/list/delete** | CRUD without file stream | `src/relay_server/core/artifacts.py:166-216` |
| **Orphaned-artifact cleanup** | Deletes artifacts whose task_id no longer exists (after max_age_days) | `src/relay_server/core/artifacts.py:219-274` |
| **Upload (spooled)** | Streaming upload via `SpooledTemporaryFile` (1 MiB RAM → disk), size limit enforced | `src/relay_server/api/v2/storage.py:33-112` |
| **Download** | Artifact download via `FileResponse` | `src/relay_server/api/v2/storage.py:133-156` |
| **Delete / list / meta** | Delete artifact, list, metadata | `src/relay_server/api/v2/storage.py:115-177` |
| **Scheduler artifact upload** | Task-bound artifact upload | `src/relay_server/api/v2/scheduler.py:121-165` |
| **Chunked upload (init/chunk/complete)** | 3-phase upload for large/unreliable uploads, chunks land on disk, max 10000 chunks, size limits | `src/relay_server/core/chunked_upload.py:35-208`; `api/v2/storage.py:193-260` |
| **Checksum verification (chunked)** | Optional SHA256 check on `complete` | `src/relay_server/core/chunked_upload.py:146-185` |
| **Stale-session pruning** | Discards unfinished chunk-upload sessions after max_age | `src/relay_server/core/chunked_upload.py:199-208` |

## 9. Maintenance / Watchdogs

| Feature | Description | Implementation |
|---|---|---|
| **MaintenanceScheduler (central)** | Bundles all watchdog tasks in a registry with per-task interval | `src/relay_server/core/maintenance.py:117-289` |
| **Single maintenance loop** | One asyncio task calls `run_due` every `maintenance_interval_seconds` | `src/relay_server/main.py:109-125` |
| **Heartbeat watchdog** | Marks dead nodes offline | `core/maintenance.py:238-242` → `core/discovery.mark_offline_nodes` |
| **Claim-TTL watchdog** | Releases/fails expired claims | `core/maintenance.py:246-250` → `scheduler.release_or_fail_claims` |
| **Token cleanup** | Deletes expired token-hours | `src/relay_server/core/maintenance.py:40-51, 253` |
| **Artifact cleanup** | Orphaned-artifact sweep hourly | `core/maintenance.py:257-263` |
| **Chunked-upload cleanup** | Stale-session pruning hourly | `core/maintenance.py:266-270` |
| **Orphaned-stage cleanup** | Fails non-claimable stages | `core/maintenance.py:273-277` → `scheduler.fail_orphaned_stages` |
| **DB VACUUM** | WAL checkpoint + VACUUM daily | `src/relay_server/core/maintenance.py:59-83, 280` |
| **SSN auto-approve** | Auto-approves pending SSN worker registrations | `src/relay_server/core/maintenance.py:86-109, 285-289` |
| **Shutdown final sweep** | Last `run_all` on graceful shutdown | `src/relay_server/main.py:99-105` |

## 10. Dashboard

| Feature | Description | Implementation |
|---|---|---|
| **Dashboard HTML** | Static `dashboard.html` (read-only for human admin) | `src/relay_server/api/v2/dashboard.py:144-148` |
| **Login page** | Login form for user or seed, sets CSRF cookie | `src/relay_server/api/v2/dashboard.py:151-156, 181-241` |
| **Bootstrap page** | Create the first human admin after seed login | `src/relay_server/api/v2/dashboard.py:252-288` |
| **Change-password page** | Mandatory page for `force_password_change` users | `src/relay_server/api/v2/dashboard.py:244-249` |
| **Logout** | Deletes session and CSRF cookie | `src/relay_server/api/v2/dashboard.py:291-299` |
| **Static-file server** | Serves JS/CSS with `no-cache` (path-traversal protection) | `src/relay_server/api/v2/dashboard.py:165-178` |
| **Overview API** | Aggregated cluster statistics (nodes, tasks, stages, artifacts, status counts) | `src/relay_server/api/v2/dashboard.py:320-428` |
| **Endpoints listing** | Static list of all v2 API endpoints | `src/relay_server/api/v2/dashboard.py:431-435, 797-996` |
| **Recent-events API** | Recent events from event-bus history | `src/relay_server/api/v2/dashboard.py:438-448` |
| **Capabilities API (session)** | Capabilities of online nodes (for SSN pages) | `src/relay_server/api/v2/dashboard.py:451-467` |
| **Task submit (session)** | Simple task from a capability page | `src/relay_server/api/v2/dashboard.py:470-494` |
| **Task status (session)** | Task status for a capability page | `src/relay_server/api/v2/dashboard.py:497-513` |
| **RBAC management API** | Users/groups/permissions CRUD via session cookie | `src/relay_server/api/v2/dashboard.py:642-785` |
| **Me API** | Current user with permissions | `src/relay_server/api/v2/dashboard.py:302-317` |
| **Dashboard JS** | `dashboard.js`, `login.js`, `bootstrap.js`, `change-password.js` | `src/relay_server/static/*.js` |

## 11. SSN (Server-Side Node)

| Feature | Description | Implementation |
|---|---|---|
| **SSN autostart/stop** | Starts/stops SSN systemd-user unit on server start/shutdown | `src/relay_server/main.py:84-90, 148-171` |
| **SSN capability pages** | Dashboard requests `ssn.capability-pages` capability via a task for available pages | `src/relay_server/api/v2/dashboard.py:516-639` |
| **SSN pages cache** | 30 s TTL cache avoids a task per page view | `src/relay_server/api/v2/dashboard.py:79-85, 602-624` |
| **SSN pages API** | `/api/ssn-pages` returns capability pages with dynamic-route URLs | `src/relay_server/api/v2/dashboard.py:627-639` |
| **SSN auto-approve (maintenance)** | Auto-approves pending SSN registrations | `src/relay_server/core/maintenance.py:86-109` |
| **SSN pages dir** | Server reads pages from `~/.ssn/pages` directly | `src/relay_server/config.py:62-65` |
| **SSN proxy (HTMX server)** | Localhost:8790, proxies task-submit/status/storage, hosts mflux capability page | `nodes/common/ssn_proxy.py` |
| **SSN-proxy relay endpoints** | `/api/task-submit`, `/api/tasks/{id}`, `/api/storage/{id}` proxy with SSN token | `nodes/common/ssn_proxy.py:97-129` |
| **mflux capability page (HTMX)** | Image-generation UI, submit→poll→show, base64-inline image | `nodes/common/ssn_proxy.py:137-295` |
| **Page-marker files** | SSN writes marker HTML for `image.generate.mflux` under `~/.ssn/pages` | `nodes/common/ssn_proxy.py:83-89` |

## 12. Dynamic Node Routes (T-075)

| Feature | Description | Implementation |
|---|---|---|
| **Route declaration (heartbeat)** | Nodes declare API routes in capability YAML, transmitted on heartbeat | `src/relay_server/core/discovery.py:44-64, 178-183`; `models/__init__.py:332-338` |
| **node_routes table** | Stores declared routes per node (path, method, auth, upstream) | `src/relay_server/core/db.py:265-276` |
| **Route proxy** | Intercepts `/dashboard/api/node-routes/{node_id}/...`, checks auth mode, proxies via httpx | `src/relay_server/core/route_registry.py:38-113` |
| **Auth modes for routes** | `session`, `node_token` (Bearer), `none` (public) | `src/relay_server/core/route_registry.py:60-69` |
| **Routes cleanup on offline** | Routes for offline nodes are deleted | `src/relay_server/core/discovery.py:520-523` |

## 13. Docs

| Feature | Description | Implementation |
|---|---|---|
| **Docs index** | Lists allowed Markdown docs as JSON | `src/relay_server/api/v2/docs.py:127-138` |
| **Docs rendering** | Renders whitelist Markdown as HTML with dark theme | `src/relay_server/api/v2/docs.py:97-124, 141-152` |
| **Link rewriting** | Internal `.md` links become `/relay/v2/docs/{name}` | `src/relay_server/api/v2/docs.py:73-94` |
| **Legacy aliases** | Old doc names keep working | `src/relay_server/api/v2/docs.py:49-70` |

## 14. CLI — Server

| Feature | Description | Implementation |
|---|---|---|
| **Server command** | `relay server [--host] [--port] [--enable-master-seed] [--config]` starts uvicorn | `src/relay_server/main.py:288-323` |
| **Admin command** | `relay admin init-master` generates the master seed | `src/relay_server/main.py:305-342` |

## 15. CLI — Node (`node-cli`)

| Feature | Description | Implementation |
|---|---|---|
| **Daemon control** | `daemon start/stop/restart/status/foreground` with PID file, SIGHUP reload | `nodes/common/node_cli.py:521-884` |
| **Heartbeat one-shot** | `node-cli heartbeat` | `nodes/common/node_cli.py:890-898` |
| **Claim one-shot** | `node-cli claim <capability>` shows capability_details | `nodes/common/node_cli.py:901-922` |
| **Complete one-shot** | `node-cli complete <stage_id> --task --result-file` | `nodes/common/node_cli.py:925-940` |
| **Task submit** | `node-cli task submit --stage <cap>:<json> [--priority] [--owner]` | `nodes/common/node_cli.py:960-974` |
| **Task result** | `node-cli task result <task_id>` with stages/artifacts/notes/handler-info | `nodes/common/node_cli.py:977-988, 1049-1090` |
| **Task wait** | `node-cli task wait <task_id>` polls until done, shows new notes live | `nodes/common/node_cli.py:1010-1046` |
| **Task note** | `node-cli task note <task_id> <message>` | `nodes/common/node_cli.py:991-1006` |
| **Artifact download** | `node-cli artifact download <id> [--output]` streaming, token refresh | `nodes/common/node_cli.py:394-491, 1108-1116` |
| **Artifact upload** | `node-cli artifact upload <file> [--name] [--task-id] [--stage-id]` | `nodes/common/node_cli.py:445-484, 1119-1135` |
| **Capabilities list/validate/publish** | Profiles in `capabilities.d/`, atomic publish, SIGHUP to daemon | `nodes/common/node_cli.py:1296-1349` |
| **Capabilities diff/current** | Diff working vs. active, show active profile | `nodes/common/node_cli.py:1352-1405` |
| **Capabilities server-query** | `node-cli capabilities server` / `info <name>` from relay | `nodes/common/node_cli.py:1408-1485` |
| **Node list/info** | `node-cli node list` / `node info <id>` from relay | `nodes/common/node_cli.py:1488-1592` |
| **Status** | `node-cli status` shows worker_status.json | `nodes/common/node_cli.py:1599-1609` |
| **Reload** | `node-cli reload` sends SIGHUP to daemon | `nodes/common/node_cli.py:1612-1623` |
| **Docs (T-059)** | `node-cli docs [name]` reads relay docs, HTML→text | `nodes/common/node_cli.py:1142-1248` |
| **Update check/apply (T-062)** | `node-cli update check` (git fetch, behind-count), `update apply` (git pull + systemd restart) | `nodes/common/node_cli.py:1255-1289`; `core/node_utils.py:100-231` |
| **JSON output** | `--json` for all commands (scripting) | distributed in `node_cli.py` |
| **Env-var overrides** | `RELAY_BASE_URL`, `RELAY_HEARTBEAT_INTERVAL`, `RELAY_CLAIM_INTERVAL`, `RELAY_MAX_RETRIES` | `nodes/common/node_cli.py:115-139` |
| **Capability env overrides** | `RELAY_CAPABILITY_<NAME>_HANDLER`/`_MAX_PARALLEL` per capability | `nodes/common/capability_loader.py:196-222` |
| **Token refresh on 401/403** | RelayClient refreshes token once, retries request | `nodes/common/node_cli.py:198-258` |

## 16. Nodes — Daemon (`node-daemon`)

| Feature | Description | Implementation |
|---|---|---|
| **SSE-driven daemon** | Replaces polling loop with SSE event stream, reacts to `stage_claimed`/`task_created` | `nodes/common/node_daemon.py` (whole module) |
| **Heartbeat thread** | Identical to node-cli daemon | `nodes/common/node_daemon.py:150-178` |
| **SSE reconnect** | Auto-reconnect after 5 s on connection loss | `nodes/common/node_daemon.py:79, 189-219` |
| **Per-task failure counter** | Stops reclaiming after `max_retries` (mirror of server) | `nodes/common/node_daemon.py:102-104, 310-327` |
| **max_parallel enforcement** | Per-capability `_in_flight` counter, sequential execution | `nodes/common/node_daemon.py:336-388` |

## 17. Nodes — Capability System

| Feature | Description | Implementation |
|---|---|---|
| **Capability data model** | `Capability`, `CapabilitySet`, `CapabilityType` (ai/tool/script/workflow/resource) | `nodes/common/capability.py` |
| **Input-schema validation** | Fields with required/default/enum/ge/le, payload validated locally | `nodes/common/capability.py:63-230` |
| **Capability diff** | Compares two CapabilitySets (added/removed/changed) | `nodes/common/capability.py:470-507` |
| **YAML profiles** | Capabilities in `~/.relay/capabilities.d/*.yaml`, active profile in `capabilities.active.yaml` | `nodes/common/capability_loader.py:131-135` |
| **JSON-schema validation** | Draft 2020-12 schema for profiles + structural fallback | `nodes/common/capability_loader.py:45-125` |
| **Profile publish** | Validates + atomically copies to active file | `nodes/common/capability_loader.py:488-507` |
| **Profile diff** | `diff_profiles` compares normalized lists | `nodes/common/capability_loader.py:510-538` |
| **Active-profile cache** | Thread-safe mtime-cached loader (re-read on mtime change), SIGHUP invalidates | `nodes/common/capability_loader.py:545-597` |
| **Handler runner** | Runs handler as subprocess, payload on stdin, env vars, timeout, JSON result on stdout, error handling | `nodes/common/handler_runner.py:103-190` |
| **Handler contract** | Exit 0 → JSON stdout, non-zero → error; `_handler` diagnostics in result | `nodes/common/handler_runner.py:28-43, 159-190` |

## 18. Storage-Node (Example Node)

| Feature | Description | Implementation |
|---|---|---|
| **Storage handlers** | archive (download+write), delete, list, quota | `nodes/storage-node/storage_node.py:57-142` |
| **Path-traversal protection** | `_safe_path` resolves against base, refuses escape | `nodes/storage-node/storage_node.py:42-54` |
| **Quota threshold** | `RELAY_QUOTA_THRESHOLD`, posts cleanup task when exceeded | `nodes/storage-node/storage_node.py:27, 129-170` |
| **Cleanup-task posting** | Posts `llm.decide_cleanup` task to relay | `nodes/storage-node/storage_node.py:145-170` |
| **Registration** | `register.py` registers node with storage.* capabilities | `nodes/storage-node/register.py` |
| **Docker compose** | Container setup for storage node | `nodes/storage-node/docker-compose.yml` |

## 19. mDNS / Zeroconf

| Feature | Description | Implementation |
|---|---|---|
| **mDNS advertisement** | Registers `_http._tcp` service as `ai-relay.local` with health path/version | `src/relay_server/core/zeroconf.py:36-95` |
| **Local-IP detection** | UDP-connect trick for routable local IP | `src/relay_server/core/zeroconf.py:19-29` |
| **Startup in background** | mDNS start does not block server startup | `src/relay_server/main.py:74-77` |

## 20. Tests

| Feature | Description | Implementation |
|---|---|---|
| **Event tests** | EventBus, SSE, subscriber drop | `tests/test_events.py` |
| **Node-registry tests** | Node-ID minting, lookup, list | `tests/test_node_registry.py` |
| **Storage tests** | Artifact storage, chunked upload | `tests/test_storage.py`, `tests/test_storage_e2e.py` |
| **Zeroconf tests** | mDNS registration | `tests/test_zeroconf.py` |
| **CLI tests** | Recovery CLI | `tests/test_cli.py` |
| **Auth tests** | Token, registration, master seed | `tests/test_auth.py` |
| **DB tests** | Schema, migrations, audit | `tests/test_db.py` |
| **Discovery tests** | Heartbeat, capabilities, offline | `tests/test_discovery.py` |
| **Maintenance tests** | Scheduler, watchdogs | `tests/test_maintenance.py`, `tests/test_scheduler.py` |
| **Rate-limit tests** | slowapi integration | `tests/test_rate_limit.py` |
| **SSN tests** | Server-side node | `tests/test_ssn.py` |
| **Route-registry tests** | Dynamic node routes | `tests/test_route_registry.py` |
| **Dashboard tests** | Login, RBAC, overview | `tests/test_dashboard.py` |
| **Node tests** | Capability loader, handler runner, example nodes, node-CLI, node-daemon | `tests/nodes/*.py` |
| **Manual node test** | Manual integration test | `scripts/manual_node_test.py` |

## 21. Examples / Integration

| Feature | Description | Implementation |
|---|---|---|
| **Minimal RelayClient** | Standalone HTTP client for external nodes (register, heartbeat, claim, complete, SSE) | `examples/nodes/relay_client.py` |
| **Approval-wait helper** | Waits for admin approval, polls with temp token | `examples/nodes/relay_client.py:227-264` |
| **SSE client example** | Example for SSE consumption | `examples/sse_client.py` |
| **Example nodes** | approve_nodes, board_node, vault_node with node_base | `examples/nodes/*.py` |
| **Agent integration** | relay-task.py (task poller), ai-relay-agent-poller.py | `examples/agent-integration/*.py` |
| **Capabilities example** | Sample capabilities.yaml | `examples/capabilities.yaml` |
| **Config example** | Sample config.yaml | `examples/config.yaml` |
| **Dist storage-node bundle** | Distributable bundle with poller.py | `dist/storage-node-bundle/*.py` |

## 22. Deployment / Ops

| Feature | Description | Implementation |
|---|---|---|
| **systemd units** | Service definitions for server, node-CLI, SSN | `systemd/` |
| **Makefile** | Build/test hooks | `Makefile` |
| **uv/pyproject** | Project config with uv locking | `pyproject.toml`, `uv.lock` |
| **Hermes plans** | Task-planning docs per feature/task | `.hermes/plans/*.md` |
| **Hermes opencode output** | Status/tasks/decisions/verification per plan | `.hermes/opencode-output/*/` |
| **Example node_cli.spec** | Spec documentation | (referenced in node_cli.py docstring) |