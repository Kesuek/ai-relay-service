# AI Relay Storage Node

A KI-less storage service node for the AI Relay. It registers with the relay
using storage capabilities, writes files to a NAS mount, and can post service
tasks back to the relay for AI-capable nodes to decide on.

## Capabilities

- `storage.archive` — move artifacts from the relay to NAS storage
- `storage.list` — list archived files on NAS
- `storage.delete` — delete archived files
- `storage.quota` — report disk space status

## Quick Start

### 1. Build the image

```bash
cd nodes/storage-node
docker build -t ai-relay-storage-node:latest .
```

### 2. Run on the NAS

```bash
docker run -d \
  --name ai-relay-storage \
  -v /volume1/ai-relay-storage:/storage \
  -v ai-relay-agent-config:/root/.relay \
  -e RELAY_BASE_URL=http://192.168.2.100:8788 \
  -e RELAY_NODE_NAME=nas-storage-01 \
  -e RELAY_STORAGE_PATH=/storage \
  -e RELAY_POLL_INTERVAL=8 \
  -e RELAY_QUOTA_THRESHOLD=0.85 \
  --restart unless-stopped \
  ai-relay-storage-node:latest
```

### 3. Register the node

If the node is not registered yet, run:

```bash
docker exec ai-relay-storage python /app/register.py
```

### 4. Approve the node in the relay

If the node is still pending, approve it via the relay dashboard or the admin API:

```bash
curl -H "Authorization: Bearer ${RELAY_ADMIN_TOKEN}" \
  -X POST \
  http://192.168.2.100:8788/relay/v2/admin/nodes/${NODE_ID}/approve \
  -d '{"role":"service","capabilities":[{"name":"storage.archive","version":"1.0.0"}]}'
```

## Flow

1. A worker (for example the Mac worker) generates an image.
2. The worker uploads the image to `POST /relay/v2/storage/upload` and receives
   an `artifact_id`.
3. The worker posts a task with a `storage.archive` stage and a
   `target_path` payload.
4. The storage node claims the stage automatically.
5. The storage node downloads the file from the relay and writes it to
   `/storage/<target_path>` on the NAS.
6. The storage node marks the stage as complete.

## Service Tasks from the Storage Node

The storage node can post tasks back to the relay when an AI decision is needed.
For example, when disk usage crosses the configured threshold:

```json
{
  "task_name": "storage.cleanup_request.123456",
  "stages": [
    {
      "stage_name": "decide",
      "capability": "llm.decide_cleanup",
      "payload": {
        "storage_path": "/storage",
        "usage_ratio": 0.91,
        "threshold": 0.85
      }
    }
  ]
}
```

An AI-capable node can claim this task and return a list of files to delete. The
relay can then route a follow-up `storage.delete` stage for the storage node to
execute.

## Docker Compose

See [`docker-compose.yml`](docker-compose.yml).

## systemd

See [`ai-relay-storage.service`](ai-relay-storage.service).
