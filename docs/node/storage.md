# Storage Node

The storage node is a **service node** (role `service`, not `worker`)
that provides NAS-backed file storage to the relay. It is the first
concrete service image built on top of the node base image
(`docker/base/`), shipped as `docker/storage/`.

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
| `storage.upload_channel` | ✅ | Open a temp bridge route so a caller can stream a large file **to** the NAS through the relay. |
| `storage.download_channel` | ✅ | Open a temp bridge route so a caller can stream a large file **from** the NAS through the relay. |

The core handlers live in `docker/storage/handlers/*.py` and share a
common `_common.py` that enforces the path-traversal guard `_safe_path`
(ported from the legacy `storage_node.py`) — every caller-supplied path
is resolved relative to `/storage` and rejected if it escapes after
symlink/`..` resolution.

## Bridge server (T-128) — large file handoff

For large files, the regular task-complete path (returning `data_base64`
in the result) would load the whole file into RAM. Instead, the storage
node runs a small HTTP server alongside the daemon:

- `docker/storage/bridge_server.py` — Starlette server on `0.0.0.0:8791`.
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
docker build -t ai-relay-node-base -f docker/base/Dockerfile .
docker build -t ai-relay-storage  -f docker/storage/Dockerfile .
RELAY_URL=https://relay.example.com STORAGE_DIR=/mnt/nas \
    docker compose -f docker/storage/docker-compose.yml up -d
```

The node registers on first start (status `pending`) — approve it via
the relay dashboard or `relay-recovery admin approve-node <node_id>`.