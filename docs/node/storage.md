# Storage Node

The storage node is a **service node** (role `service`, not `worker`)
that provides NAS-backed file storage to the relay. It is the first
concrete service image built on top of the node base image
(`docker/nodes/base/`), shipped as `docker/nodes/storage/`.

## What it offers

| Capability | Claimable | Description |
|------------|-----------|-------------|
| `storage.store` | ✅ | Write a file to the NAS (inline `data_base64` or stream an artifact by `artifact_id`). |
| `storage.fetch` | ✅ | Read a file back as `data_base64` (small files). |
| `storage.delete` | ✅ | Remove a file or directory (recursive). |
| `storage.list` | ✅ | List files under a prefix. |
| `storage.quota` | ✅ | Report disk usage + threshold (`RELAY_STORAGE_QUOTA_THRESHOLD`, default 0.9). |
| `storage.stat` | ✅ | Stat a single path (size, mtime, is_dir). |
| `storage.move` | ✅ | Rename/move a file or directory. |
| `storage.extract` | ✅ | Unpack a stored `.tar.gz` into a directory (T-135). |
| `storage.archive` | ✅ | Pack a directory into a `.tar.gz` (T-135). |
| `storage.upload_channel` | ✅ | Open a temp bridge route so a caller can stream a large file **to** the NAS through the relay. |
| `storage.download_channel` | ✅ | Open a temp bridge route so a caller can stream a large file **from** the NAS through the relay. |
| `backup.create` | ✅ | Declare an upload as a versioned backup (full or incremental). |
| `backup.list` | ✅ | List backups, optionally filtered by `source`/`type`. |
| `backup.info` | ✅ | Return the manifest of a single backup. |
| `backup.restore` | ✅ | Return a backup's data (inline `data_base64` for small backups). |
| `backup.delete` | ✅ | Mark a backup `deleted` (manifest kept for audit, data removed). |
| `backup.retention` | ✅ | Apply a retention policy to a source (keep_last / max_age_days / GFS). |

The core handlers live in `docker/nodes/storage/handlers/*.py` and share a
common `_common.py` that enforces the path-traversal guard `_safe_path`
(ported from the legacy `storage_node.py`) — every caller-supplied path
is resolved relative to `/storage` and rejected if it escapes after
symlink/`..` resolution.

## Bridge server (T-128) — large file handoff

For large files, the regular task-complete path (returning `data_base64`
in the result) would load the whole file into RAM. Instead, the storage
node runs a small HTTP server alongside the daemon:

- `docker/nodes/storage/bridge_server.py` — Starlette server on `0.0.0.0:8791`.
- Endpoints: `POST /upload/{channel_id}` (stream body → NAS) and
  `GET /download/{channel_id}` (stream NAS file → caller).
- **Source-IP-Allowlist middleware**: every request's source IP is
  validated against the relay server's IP. The server IP is resolved at
  startup from the `RELAY_URL` hostname (DNS) and cached; an explicit
  `RELAY_SERVER_IP` env overrides the resolution. Non-matching → 403;
  unresolved → fail-closed (403 on every request).

The storage Dockerfile starts the bridge server in the background and
then execs the base entrypoint (which execs `node-daemon`). Both
processes share the container; `tini` (PID 1) reaps the background
process.

## Bridge channel flow (T-129)

```
Caller                Relay (proxy)            Storage bridge server        NAS
  │                       │                          │                    │
  │ submit upload_channel │                          │                    │
  │──────────────────────>│                          │                    │
  │                       │ claim → run upload_channel handler             │
  │                       │ handler: register_temp_route (/upload/ch_x)  │
  │                       │ handler: complete {upload_url, channel_id, ttl}
  │<──── upload_url ──────│                          │                    │
  │                       │                          │                    │
  │ POST upload_url       │                          │                    │
  │──────────────────────>│                          │                    │
  │                       │  stream body chunkwise   │                    │
  │                       │─────────────────────────>│ write chunkwise    │
  │                       │                          │───────────────────>│
  │<──── 200 ─────────────│<─────────────────────────│                    │
```

The relay proxy in `route_registry.py` streams both the **request body**
(`request.stream()`) and the **upstream response**
(`client.send(stream=True)` + `StreamingResponse`) chunkwise — large
files never sit fully in the relay's RAM. `_forward_headers` keeps
`content-length` so the upstream knows the body size.

`storage.download_channel` is the symmetric path (GET, stream the file
back to the caller).

## Source-IP allowlist configuration

| Env | Default | Description |
|-----|---------|-------------|
| `RELAY_SERVER_IP` | _(resolved from RELAY_URL)_ | Explicit relay server IP the bridge server accepts requests from. Bypasses DNS resolution. |
| `RELAY_TRUST_FORWARDED_FOR` | `0` | Set to `1` to honour `X-Forwarded-For` (only when the bridge server sits behind an L7 proxy you control). By default the socket peer IP is authoritative. |
| `RELAY_STORAGE_PATH` | `/storage` | Base directory for all stored files. |
| `RELAY_STORAGE_QUOTA_THRESHOLD` | `0.9` | Usage ratio at which `storage.quota` reports `threshold_exceeded`. |
| `BRIDGE_PORT` | `8791` | Port the bridge server listens on. |

## Running it

See [`docker/README.md`](../../docker/README.md) for the build + compose
walkthrough. The short version:

```
docker build -t ai-relay-node-base -f docker/nodes/base/Dockerfile .
docker build -t ai-relay-storage  -f docker/nodes/storage/Dockerfile .
RELAY_URL=https://relay.example.com STORAGE_DIR=/mnt/nas \
    docker compose -f docker/nodes/storage/docker-compose.yml up -d
```

The node registers on first start (status `pending`) — approve it via
the relay dashboard or `relay-recovery admin approve-node <node_id>`.

## Backup management (T-130/T-131/T-132)

The storage node treats backups as **versioned, identifiable artifacts**
with a JSON manifest per backup — no SQLite index (DECISIONS 2026-08-06).
Each backup lives under `<STORAGE_PATH>/backups/<backup_id>/`:

```
backups/
└── bk_<16-hex>/
    ├── manifest.json   # metadata (see below)
    └── data.bin        # the backup payload
```

### Manifest schema

| Field | Type | Description |
|-------|------|-------------|
| `backup_id` | `str` | `bk_<16-hex>`, minted by the node. |
| `source` | `str` | Logical source name (e.g. `projects`, `photos`). |
| `type` | `str` | `full` or `incremental`. |
| `base_backup_id` | `str \| null` | For `incremental`: the base backup it builds on. |
| `created_at` | `str` | ISO-8601 UTC timestamp. |
| `size_bytes` | `int` | Payload size. |
| `retention` | `null` | Reserved for future per-backup retention. |
| `status` | `str` | `active`, `expired`, or `deleted`. |

### Handler reference

**`backup.create`** — payload `{source, type, data_base64 | artifact_id, base_backup_id?}`.
Writes the payload to `data.bin` and mints a manifest. For `type:
incremental`, `base_backup_id` must reference an existing (non-deleted)
backup. Result: `{status: "created", backup_id, path, size_bytes, type}`.

**`backup.list`** — payload `{source?, type?}`. Lists active backups
(deleted ones are excluded), newest first. Result:
`{status: "listed", count, backups: [manifest, ...]}`.

**`backup.info`** — payload `{backup_id}`. Returns the full manifest.
Result: `{status: "info", ...manifest}`.

**`backup.restore`** — payload `{backup_id}`. Returns the payload inline
as `data_base64` (≤10 MB). Larger backups return `download_url: null`
(a bridge download route is a future task). Result:
`{status: "restored", backup_id, size_bytes, data_base64}`.

**`backup.delete`** — payload `{backup_id}`. Marks the manifest
`deleted` and removes `data.bin` (manifest kept for audit). Result:
`{status: "deleted", backup_id}`.

**`backup.retention`** — payload `{source, policy}`. Applies a retention
policy to a source's active backups and marks expired ones `deleted`.
Supported policy formats:

| Policy | Meaning |
|--------|---------|
| `{"keep_last": N}` | Keep the N most recent, delete older. |
| `{"max_age_days": N}` | Delete backups older than N days. |
| `{"keep_daily": N, "keep_weekly": N, "keep_monthly": N}` | GFS: keep the newest per day/week/month bucket. |

Result: `{status: "applied", source, deleted: [backup_id, ...], count}`.

### Retention watchdog

A background process (`docker/nodes/storage/retention_watchdog.py`) applies
configured retention policies periodically, analogous to the server's
`MaintenanceScheduler`. Policies are read from `~/.relay/retention.yaml`
(or `RELAY_RETENTION_CONFIG`):

```yaml
projects:
  keep_last: 2
photos:
  max_age_days: 30
```

| Env | Default | Description |
|-----|---------|-------------|
| `RELAY_RETENTION_CONFIG` | `~/.relay/retention.yaml` | Path to the retention policy config. |
| `RELAY_RETENTION_INTERVAL` | `3600` | Seconds between watchdog runs. |

The watchdog is started by the storage entrypoint alongside the bridge
server. An empty/missing config means no automatic deletion (fail-safe).

## Folder transfer as `.tar.gz` (T-133/T-135)

Directories are transferred as a single `.tar.gz` over the bridge (one
file, one upload). The **uploader decides** whether the node unpacks the
archive or stores it as-is — the storage node stays agnostic (DECISIONS
2026-08-06, no FUSE/mounting).

### `storage.store` with `action`

`storage.store` accepts an optional `action` field:

| `action` | Behaviour |
|----------|-----------|
| `store_as_is` (default) | Store the `.tar.gz` untouched (for pass-through / intermediate storage / backups). |
| `extract` | Unpack the archive into a directory named after the target path. |

```json
{"path": "bundle", "action": "extract", "data_base64": "<tar.gz>"}
```

Extraction rejects path-traversal entries (`..`, absolute paths) and
symlinks — an archive that tries to escape the target dir fails the
stage.

### `storage.extract` / `storage.archive` (T-135)

Unpacking/packing can also be requested **after** the fact, not only at
upload:

- **`storage.extract`** — payload `{path}`. Unpacks a stored `.tar.gz`
  into a directory named after the archive (minus the suffix). Result:
  `{status: "extracted", path, entries}`.
- **`storage.archive`** — payload `{path, target}`. Packs a directory
  into a `.tar.gz` at `target`. Result:
  `{status: "archived", path, size_bytes, entries}`.

Typical flow: upload a folder as `store_as_is` first, then `extract` it
later when the real directory structure is needed — or `archive` an
existing directory on demand.