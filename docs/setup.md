# AI Relay Service — Setup Guide

This guide explains how to install and run the AI Relay Service and the
KI-less Storage Node on your local network.

## What you get

- A central relay server that routes tasks between AI agents and service nodes
- A web dashboard at `http://ai-relay.local:8788/relay/v2/dashboard/`
- Optional mDNS advertisement so nodes can find the relay as `ai-relay.local`
- A storage node that archives generated media (images, audio, files) on a NAS

## Requirements

- Linux host for the relay (a small server, NAS, or always-on PC)
- Docker + Docker Compose on the NAS for the storage node
- Python 3.11+ if you want to run the relay from source
- Local network access or Tailscale

## 1. Install the relay server

### Option A: Install from source

```bash
git clone https://github.com/Kesuek/ai-relay-service.git
cd ai-relay-service
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Option B: Run with Docker (if available)

Build the relay server image:

```bash
docker build -t ai-relay-server:latest -f Dockerfile.relay .
```

> The repository currently does not include a relay-server Dockerfile. Create one
> yourself or use Option A for now.

## 2. Create the master admin seed

The master seed is required to approve nodes and create other admin tokens.

```bash
source .venv/bin/activate
relay-server admin init-master
```

Copy the printed `adm_...` secret and store it in a password manager.

## 3. Start the relay server

### With mDNS enabled (recommended)

```bash
RELAY_ENABLE_MDNS=true relay-server server --port 8788
```

The relay is now reachable as:

- `http://ai-relay.local:8788` (mDNS)
- `http://<relay-ip>:8788` (direct IP)

### With static IP only

```bash
relay-server server --port 8788
```

## 4. Storage node on the NAS

The storage node is a KI-less Docker service that stores files on your NAS.

### Download and extract the bundle (no git required)

```bash
mkdir -p /volume1/ai-relay-storage
cd /volume1/ai-relay-storage
curl -fsSL https://raw.githubusercontent.com/Kesuek/ai-relay-service/main/nodes/storage-node/docker-compose.yml -o docker-compose.yml
curl -fsSL https://raw.githubusercontent.com/Kesuek/ai-relay-service/main/nodes/storage-node/Dockerfile -o Dockerfile
curl -fsSL https://raw.githubusercontent.com/Kesuek/ai-relay-service/main/nodes/storage-node/requirements.txt -o requirements.txt
curl -fsSL https://raw.githubusercontent.com/Kesuek/ai-relay-service/main/nodes/storage-node/storage_node.py -o storage_node.py
curl -fsSL https://raw.githubusercontent.com/Kesuek/ai-relay-service/main/nodes/storage-node/poller.py -o poller.py
curl -fsSL https://raw.githubusercontent.com/Kesuek/ai-relay-service/main/nodes/storage-node/register.py -o register.py
```

> Or copy the prepared bundle from `dist/storage-node-bundle.tar.gz` in the
> repository.

### Start the container

```bash
cd /volume1/ai-relay-storage
docker compose up -d --build
```

By default it connects to `http://ai-relay.local:8788`.

If mDNS does not work in your network, override the URL:

```bash
RELAY_BASE_URL=http://192.168.2.170:8788 docker compose up -d --build
```

### Register the node with the relay

```bash
docker compose run --rm ai-relay-storage python /app/register.py
```

This writes `~/.relay/ai-relay-agent.json` and `~/.relay/ai-relay-agent.token`
inside the persistent Docker volume.

## 4. Approve or activate nodes

Every new node starts in `pending` state. An administrator must activate it
before it can claim work.

### With the dashboard

1. Open `http://ai-relay.local:8788/relay/v2/dashboard/`
2. Log in with the master seed or a human admin account
3. Go to **Nodes**
4. Find the pending node
5. Click **Approve**
6. Review the role and capabilities
7. Click **Confirm**

### With the API

First register an admin node with the master seed:

```bash
ADMIN_TOKEN=$(curl -s -X POST "http://ai-relay.local:8788/relay/v2/auth/register-admin" \
  -H "Content-Type: application/json" \
  -d "{\"node_name\":\"admin-cli\",\"bootstrap_secret\":\"${ADM_SECRET}\",\"endpoint\":null,\"capabilities\":[{\"name\":\"admin\",\"version\":\"1.0.0\"}]}" \
  | jq -r .token)
```

Then approve the pending node:

```bash
curl -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -X POST \
  "http://ai-relay.local:8788/relay/v2/admin/nodes/${NODE_ID}/approve" \
  -H "Content-Type: application/json" \
  -d '{"role":"service","capabilities":[{"name":"storage.archive","version":"1.0.0"}]}'
```

You can find `${NODE_ID}` in the agent JSON file inside the container:

```bash
docker exec ai-relay-storage cat /root/.relay/ai-relay-agent.json
```

## 5. Manage tokens

### Issue a new runtime token

If a node lost its token or the token expired before it could refresh, issue a
new runtime token:

```bash
curl -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -X POST \
  "http://ai-relay.local:8788/relay/v2/admin/nodes/${NODE_ID}/token"
```

This invalidates the previous runtime token for that node.

### Delete a node

Removing a node deletes its records, tokens, presence data, and task claims:

```bash
curl -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -X DELETE \
  "http://ai-relay.local:8788/relay/v2/admin/nodes/${NODE_ID}"
```

## 6. Verify the setup

### Health endpoint

```bash
curl http://ai-relay.local:8788/health
```

### Upload a test file

```bash
curl -F "file=@/tmp/test.txt" http://ai-relay.local:8788/relay/v2/storage/upload
```

Response:

```json
{
  "artifact_id": "art_..."
}
```

### Create an archive task

```bash
curl -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -X POST \
  http://ai-relay.local:8788/relay/v2/scheduler/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "task_name": "archive_test",
    "stages": [
      {
        "stage_name": "archive",
        "capability": "storage.archive",
        "payload": {
          "artifact_id": "art_...",
          "target_path": "test.txt"
        }
      }
    ]
  }'
```

After a few seconds the storage node claims the task and writes the file to
`/volume1/ai-relay-storage/test.txt`.

## 7. Systemd service for the relay

Create `/etc/systemd/system/ai-relay.service`:

```ini
[Unit]
Description=AI Relay Service
After=network.target

[Service]
Type=simple
User=felix
WorkingDirectory=/home/felix/projects/ai-relay-service
ExecStart=/home/felix/projects/ai-relay-service/.venv/bin/relay-server server --port 8788
Environment=RELAY_ENABLE_MDNS=true
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable ai-relay.service
sudo systemctl start ai-relay.service
```

## 8. Updating

Pull the latest code, reinstall, and restart:

```bash
cd ai-relay-service
git pull
source .venv/bin/activate
pip install -e ".[dev]"
sudo systemctl restart ai-relay.service
```

For the storage node:

```bash
cd /volume1/ai-relay-storage
docker compose pull
docker compose up -d --build
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `ai-relay.local` not found | Use the relay's IP address directly |
| Storage node cannot register | Check that the relay is reachable from the NAS |
| mDNS blocks startup | Update to the latest relay-server version; mDNS now starts asynchronously |
| Port 8788 already in use | Stop the old relay process first |
| Node stays pending | Approve it in the dashboard or via admin API |

## Security notes

- The master seed (`adm_...`) is equivalent to root access. Store it securely.
- Runtime tokens (`rt_...`) are stored in `~/.relay/` by default.
- Do not commit tokens or the master seed to git.
- Keep the relay behind your firewall; it is designed for private networks.
