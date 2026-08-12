# Storage Node on QNAP Container Station

The **Storage Node** (`ai-relay-storage`) is a NAS storage service for the
AI-Relay service. It stores files, manages backups, and transfers folders as
`.tar.gz` — ideal for a QNAP as central storage.

This image is built for **x86_64 (Intel/AMD)** QNAP models.

## Prerequisites

- QNAP with **Container Station** (QTS/QuTS hero)
- x86_64 CPU (Intel/AMD) — ARM models need a separate image
- A running **Relay server** (the storage node connects to it)

## Installation

### 1. Load the image

**Option A — directly from GHCR (recommended):**

The image is public on the GitHub Container Registry. The QNAP can pull it
directly — no login required:

```bash
docker pull ghcr.io/kesuek/ai-relay-storage:latest
```

**Option B — from the release asset:**

Download the release asset `ai-relay-storage-bundle.tar` from the
[Releases page](https://github.com/Kesuek/ai-relay-service/releases) and load
it into Docker:

```bash
# On the QNAP (via SSH) or in Container Station:
docker load -i ai-relay-storage-bundle.tar
```

The bundle contains both images: `ai-relay-storage:latest` and
`ai-relay-node-base:latest`.

### 2. Start the storage node

**Option A — via `docker run` (SSH):**

> **⚠️ Important:** Always pass `-v ai-relay-storage-state:/home/appuser/.relay`.
> Container Station does **not** create a volume automatically — without this
> volume the node loses its identity (node_id + token) on every restart and
> re-registers itself.

```bash
docker run -d \
  --name ai-relay-storage \
  --restart unless-stopped \
  -e RELAY_URL=http://<relay-ip>:8788 \
  -e NODE_NAME=storage-node \
  -e NODE_ENDPOINT=http://<qnap-ip>:8791 \
  -v /share/Container/ai-relay-storage:/storage \
  -v ai-relay-storage-state:/home/appuser/.relay \
  ghcr.io/kesuek/ai-relay-storage:latest
```

**Option B — via Container Station (GUI):**

> **⚠️ Important:** In the Container Station dialog, create a **volume** that
> points to `/home/appuser/.relay` (e.g. `ai-relay-storage-state`). Without this
> volume the node loses its identity on every restart.

1. Open **Container Station** → **Overview** → **Create** → **Image**.
2. Select `ghcr.io/kesuek/ai-relay-storage:latest` (or `ai-relay-storage:latest` after `docker load`).
3. Set the environment variables (see table below).
4. Mount `/storage` to a NAS folder (e.g. `/share/Container/ai-relay-storage`).
5. Create a volume for `/home/appuser/.relay` (persists the node identity).
6. Start the container.

### 3. Approve the node

The node registers itself as `pending`. Approve it in the Relay dashboard or
via the admin API:

```bash
curl -X POST http://<relay-ip>:8788/relay/v2/admin/nodes/<node_id>/approve \
  -H "Content-Type: application/json" \
  -d '{"role":"service","capabilities":[{"name":"storage.store","version":"1.0.0"}]}'
```

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `RELAY_URL` | no* | mDNS discovery | Relay base URL, e.g. `http://192.168.1.50:8788`. **If unset, the node finds the relay via mDNS on the LAN** (T-152). |
| `NODE_NAME` | no | hostname | Display name in the dashboard |
| `NODE_ENDPOINT` | no | auto (own IP) | Endpoint through which the relay reaches the node (for bridge routes). **Derived automatically from the node IP + port 8791** — only set if the relay cannot reach the node directly. |
| `NODE_ROLE` | no | `worker` | `service` for storage (set in the image) |
| `NODE_REGISTRATION_SECRET` | no | — | Pre-created `rs_...` secret for registration |
| `RELAY_SERVER_IP` | no | from RELAY_URL | Explicit relay server IP for the bridge source-IP allowlist. **Resolved automatically: `RELAY_SERVER_IP` → `RELAY_URL` → mDNS.** Only set if neither `RELAY_URL` nor mDNS yields a resolvable IP. |
| `RELAY_STORAGE_PATH` | no | `/storage` | Base directory for files (set in the image) |

> **`RELAY_URL` is optional (T-152).** If you omit it, the node finds the relay
> via mDNS on the local network (the relay advertises itself as
> `ai-relay.local`). This works when relay + node are on the same LAN.
>
> The bridge allowlist (`storage.upload_channel`/`download_channel`) resolves
> the relay IP through the same cascade: **`RELAY_SERVER_IP` → `RELAY_URL` →
> mDNS**. So in an mDNS-only deployment (no `RELAY_URL`, no
> `RELAY_SERVER_IP`) the allowlist still gets the relay IP from mDNS. You only
> need `RELAY_SERVER_IP` explicitly when mDNS is unavailable **and** the relay
> is not resolvable via DNS.

## Volumes

| Mount | Purpose |
|-------|---------|
| `/storage` | NAS export — the actual files/backups. Bind-mount to a QNAP folder. |
| `/home/appuser/.relay` | Node meta + token (persists identity across restarts). Named volume. |

> **⚠️ Important for updates:** The volume `ai-relay-storage-state` (→ `/home/appuser/.relay`)
> must stay **mounted** on restart. If you delete and recreate the container
> without mounting the volume, the node loses its `ai-relay-agent.json`
> (node_id + token) and re-registers — it gets a new node ID and must be
> approved again. Always pass `-v ai-relay-storage-state:/home/appuser/.relay`
> on `docker run`.

## Capabilities

The storage node provides:

- **Files:** `storage.store` / `fetch` / `delete` / `list` / `quota` / `stat` / `move`
- **Large files:** `storage.upload_channel` / `storage.download_channel` (bridge routes)
- **Backups:** `backup.create` / `list` / `info` / `restore` / `delete` / `retention`
- **Folders:** `storage.extract` / `storage.archive` (`.tar.gz`)

## Troubleshooting

- **`Connection refused` on start:** The relay is unreachable. Check `RELAY_URL` and that the relay is running.
- **Node stays `pending`:** Not yet approved. Approve in the dashboard.
- **Bridge routes don't work:** Set `RELAY_SERVER_IP` explicitly if the QNAP does not resolve the relay via DNS.
- **Files don't land on the NAS:** Check the `/storage` mount (must point to a real QNAP folder).

## Source code

The storage node lives in the repo under `docker/nodes/storage/`. The base
image is under `docker/nodes/base/`. See `docs/node/storage.md` for the full
architecture.
