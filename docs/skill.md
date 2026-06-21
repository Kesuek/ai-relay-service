# AI Relay Service — Agent Skill Reference

This document is written for AI agents and autonomous workers. It explains what
the AI Relay Service is, which local scripts and services must run, and how to
set up or guide a human user through setup.

## 1. What is AI Relay Service?

AI Relay Service is a local task router for AI agents and service nodes.

- **Core server** (`relay-server`) runs on a host in the local network.
- **Nodes** register with the relay, advertise capabilities, and claim tasks.
- **Tasks** contain one or more stages; each stage requires a specific capability.
- **Service nodes** are KI-less workers that execute raw actions (storage, file
  system, API calls).
- **KI nodes** handle reasoning, decisions, and conversations.
- **mDNS support** lets nodes discover the relay as `ai-relay.local`.

Key concept: **the relay decides who does what; nodes only execute.**

## 2. When should an agent use this reference?

Use this skill when:

- The user asks about AI Relay setup, troubleshooting, or architecture.
- The user wants to add a new worker or service node.
- Generated files (images, audio) must be archived centrally.
- A node cannot connect to the relay or stays in "pending" state.
- The user needs to approve nodes, create tasks, or inspect the dashboard.

## 3. Required local services and scripts

### 3.1 Relay server (must run centrally)

Repository: `https://github.com/Kesuek/ai-relay-service`
Local path (on the relay host): `/home/felix/projects/ai-relay-service`

Run it with:

```bash
cd /home/felix/projects/ai-relay-service
source .venv/bin/activate
RELAY_ENABLE_MDNS=true relay-server server --port 8788
```

Health check:

```bash
curl http://ai-relay.local:8788/health
```

Make it permanent with systemd:

```bash
sudo systemctl enable ai-relay.service
sudo systemctl start ai-relay.service
```

### 3.2 Storage node (runs on NAS)

Path on NAS: `/volume1/ai-relay-storage`

Must be running:

```bash
cd /volume1/ai-relay-storage
docker compose up -d
```

Must be registered once:

```bash
docker compose run --rm ai-relay-storage python /app/register.py
```

Must be approved via the dashboard before it can claim tasks.

### 3.3 Mac worker node (optional, image generation)

If the user has a Mac worker that runs mflux/MLX image generation, it should
register as a node with capability `image.generate` and, after generating an
image, upload it to the relay storage endpoint and create a `storage.archive`
task.

This node usually runs on `m4-macmini-01` (`100.64.0.5`).

## 4. Important scripts and files

| Path | Purpose |
|------|---------|
| `src/relay_server/main.py` | Main server entry point |
| `src/relay_server/core/zeroconf.py` | mDNS advertisement |
| `src/relay_server/api/v2/storage.py` | Upload/download/meta endpoints |
| `nodes/storage-node/storage_node.py` | KI-less storage worker |
| `nodes/storage-node/poller.py` | Generic relay poller for service nodes |
| `nodes/storage-node/register.py` | One-time node registration |
| `examples/nodes/node_base.py` | Base class for custom nodes |
| `scripts/manual_node_test.py` | Manual end-to-end test |
| `docs/setup.md` | Human setup guide |

## 5. Common operations

### 5.1 Check if relay is alive

```bash
curl http://ai-relay.local:8788/health
```

### 5.2 Find the relay IP if mDNS fails

```bash
ip route get 8.8.8.8 | head -1
```

Then use `http://<relay-ip>:8788`.

### 5.3 List pending nodes (admin only)

```bash
curl -H "Authorization: Bearer ${REL...}" \
  http://ai-relay.local:8788/relay/v2/admin/nodes
```

### 5.4 Approve a node (admin only)

```bash
curl -H "Authorization: Bearer ${REL...}" \
  -X POST \
  http://ai-relay.local:8788/relay/v2/admin/nodes/${NODE_ID}/approve \
  -d '{"role":"service","capabilities":[{"name":"storage.archive","version":"1.0.0"}]}'
```

### 5.5 Upload a file to the relay

```bash
curl -F "file=@generated_image.png" \
  http://ai-relay.local:8788/relay/v2/storage/upload
```

Returns `{"artifact_id": "art_..."}`.

### 5.6 Create an archive task for the storage node

```bash
curl -H "Authorization: Bearer ${REL...}" \
  -X POST \
  http://ai-relay.local:8788/relay/v2/scheduler/tasks \
  -d '{
    "task_name": "archive_image",
    "stages": [
      {
        "stage_name": "archive",
        "capability": "storage.archive",
        "payload": {
          "artifact_id": "art_...",
          "target_path": "2026/06/image_01.png"
        }
      }
    ]
  }'
```

## 6. Decision tree: what should the agent do?

### If the user says "I want to set up AI Relay"

1. Check if the relay host has the repository cloned and venv installed.
2. If not, guide the user through `docs/setup.md` steps 1–3.
3. Check if `ai-relay.service` is running; if not, create and enable it.
4. If storage is needed, guide the user through the storage node setup.

### If a node cannot connect

1. Check relay health: `curl http://ai-relay.local:8788/health`
2. If mDNS fails, switch to IP address.
3. Check that the node is approved (dashboard or admin API).
4. Check `~/.relay/ai-relay-agent.json` for correct `node_id`.

### If a generated image must be archived

1. POST file to `/relay/v2/storage/upload` → get `artifact_id`.
2. POST task with `capability: storage.archive` and `target_path`.
3. The storage node will claim and execute the task.

### If the user wants a new worker node

1. Recommend `examples/nodes/node_base.py` as a starting point.
2. Register the node with `POST /relay/v2/auth/register`.
3. Save `node_id` and `registration_secret` to `~/.relay/`.
4. Poll `POST /relay/v2/auth/status` until approved.
5. Run heartbeat + claim loop.

## 7. Environment variables

| Variable | Default | Meaning |
|----------|---------|---------|
| `RELAY_ENABLE_MDNS` | `false` | Advertise `ai-relay.local` via mDNS |
| `RELAY_MDNS_HOSTNAME` | `ai-relay` | mDNS hostname |
| `RELAY_BASE_URL` | `http://ai-relay.local:8788` | Storage node relay URL |
| `RELAY_NODE_NAME` | `nas-storage-01` | Storage node name |
| `RELAY_STORAGE_PATH` | `/volume1/ai-relay-storage` | NAS mount path |
| `RELAY_POLL_INTERVAL` | `8` | Seconds between heartbeats/claims |
| `RELAY_QUOTA_THRESHOLD` | `0.85` | Disk usage threshold for cleanup requests |

## 8. Capability registry

Known capabilities in this ecosystem:

| Capability | Owner | Purpose |
|------------|-------|---------|
| `storage.archive` | storage node | Move relay artifacts to NAS |
| `storage.list` | storage node | List archived files |
| `storage.delete` | storage node | Delete archived files |
| `storage.quota` | storage node | Report disk usage |
| `llm.decide_cleanup` | KI node | Decide which files to delete |
| `image.generate` | Mac worker | Generate images with mflux |
| `chat`, `code`, `web`, `vision` | Hermes / agent | General agent work |

You can invent new capabilities, but tasks must reference them exactly.

## 9. Quick command reference

```bash
# relay status
curl http://ai-relay.local:8788/health

# storage node logs
docker logs -f ai-relay-storage

# storage node registration file
docker exec ai-relay-storage cat /root/.relay/ai-relay-agent.json

# list nodes (admin)
curl -H "Authorization: Bearer ${REL...}" \
  http://ai-relay.local:8788/relay/v2/admin/nodes

# upload file
curl -F "file=@file.png" http://ai-relay.local:8788/relay/v2/storage/upload
```

## 10. Safety rules

- Never commit `adm_...` (master seed) or `rt_...` (runtime tokens) to git.
- The master seed is equivalent to root; store it in a password manager.
- Tokens live in `~/.relay/`; protect that directory.
- AI Relay is designed for private networks. Do not expose port 8788 to the
  public internet without a reverse proxy and authentication.
- If you are unsure about a command, ask the user before executing it.
- If the user says "ok halt", stop deep debugging and pivot to a simpler
  strategy.
