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

## 2. Configure the session secret

The relay signs dashboard session cookies with a **session secret** — a random
string of at least 32 characters. This secret must be set **before** the server
starts, otherwise the server refuses to boot.

Create `~/.relay/config.yaml`:

```yaml
# ~/.relay/config.yaml
session_secret: "<generate a random 32+ char string, e.g. openssl rand -base64 32>"
```

Alternatively, set the `RELAY_SESSION_SECRET` environment variable:

```bash
export RELAY_SESSION_SECRET="<your-random-secret>"
```

> **Important:** The session secret is a **persistent** key. Changing it
> invalidates all existing dashboard session cookies, forcing every admin to
> log in again. Generate it once and keep it stable.

## 3. Create the master admin seed

The master seed is required for initial bootstrap and recovery. Create it once
on the relay host:

```bash
source .venv/bin/activate
relay-server admin init-master
```

Copy the printed `adm_...` secret and store it in a password manager.

> The master seed is **not** used for day-to-day work. After the first human
> admin is created through the dashboard, master-seed login is disabled until
> recovery mode is explicitly enabled.

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

## 4. Bootstrap the first human admin

When the server starts for the first time, no human admin exists. The dashboard
login form therefore shows the **Master seed** option.

1. Open `http://ai-relay.local:8788/relay/v2/dashboard/`
2. Choose **Master seed** and paste the seed from step 2
3. You are redirected to the bootstrap page
4. Enter a username (and optional email) for the first admin
5. Store the generated temporary password securely
6. Log out and log in again as the new admin
7. You are forced to change the password before you can use the dashboard

After that, master-seed login is automatically disabled. For day-to-day work,
always use human admin accounts.

## 5. Recovery mode

If all human admin accounts are locked out, enable recovery from the relay host:

```bash
relay-recovery enable-recovery --all
```

Then restart the server with recovery mode enabled:

```bash
RELAY_ENABLE_MASTER_SEED_LOGIN=true relay-server server --port 8788
```

Now the master seed can log in again and bootstrap a new admin. Once a new
admin exists and has changed the temporary password, recovery mode is no longer
needed and should be turned off.

## 6. Storage node on the NAS

The storage node is a KI-less Docker service that stores files on your NAS. The
reference implementation is in `nodes/storage-node/`. It uses the generic poller
from `nodes/common/poller.py` for relay communication.

### Download and extract the bundle (no git required)

```bash
mkdir -p /volume1/ai-relay-storage
cd /volume1/ai-relay-storage
curl -fsSL https://raw.githubusercontent.com/Kesuek/ai-relay-service/main/nodes/storage-node/docker-compose.yml -o docker-compose.yml
curl -fsSL https://raw.githubusercontent.com/Kesuek/ai-relay-service/main/nodes/storage-node/Dockerfile -o Dockerfile
curl -fsSL https://raw.githubusercontent.com/Kesuek/ai-relay-service/main/nodes/storage-node/requirements.txt -o requirements.txt
curl -fsSL https://raw.githubusercontent.com/Kesuek/ai-relay-service/main/nodes/storage-node/storage_node.py -o storage_node.py
curl -fsSL https://raw.githubusercontent.com/Kesuek/ai-relay-service/main/nodes/common/poller.py -o poller.py
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
docker compose run --rm ai-relay-storage python /app/storage_node.py --register
```

This writes `~/.relay/ai-relay-agent.json` and `~/.relay/ai-relay-agent.token`
inside the persistent Docker volume.

## 7. Approve or activate nodes

Every new node starts in `pending` state. An administrator must activate it
before it can claim work.

### With the dashboard

1. Open `http://ai-relay.local:8788/relay/v2/dashboard/`
2. Log in with a human admin account (master-seed login is only available during bootstrap or recovery)
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
curl -H "Authorization: Bearer *** \
  -X POST \
  "http://ai-relay.local:8788/relay/v2/admin/nodes/${NODE_ID}/approve" \
  -H "Content-Type: application/json" \
  -d '{"role":"service","capabilities":[{"name":"storage.archive.native","version":"1.0.0"}]}'
```

You can find `${NODE_ID}` in the agent JSON file inside the container:

```bash
docker exec ai-relay-storage cat /root/.relay/ai-relay-agent.json
```

## 8. Manage tokens

### Issue a new runtime token

If a node lost its token or the token expired before it could refresh, issue a
new runtime token via the admin API:

```bash
curl -H "Authorization: Bearer *** \
  -X POST \
  "http://ai-relay.local:8788/relay/v2/admin/nodes/${NODE_ID}/token"
```

This invalidates the previous runtime token for that node.

### Recover a lost runtime token

If the node still has its `registration_secret`, it can recover a new runtime
token itself via `/relay/v2/auth/refresh`. The server returns a new runtime
token and a new registration secret. See `docs/token-concept.md` for details.

### Delete a node

Removing a node deletes its records, tokens, presence data, and task claims:

```bash
curl -H "Authorization: Bearer *** \
  -X DELETE \
  "http://ai-relay.local:8788/relay/v2/admin/nodes/${NODE_ID}"
```

## 9. Verify the setup

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

## 10. Systemd service for the relay

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
# REQUIRED: Set RELAY_SESSION_SECRET or create ~/.relay/config.yaml with
# session_secret. Without it the server refuses to start.
# Environment=RELAY_SESSION_SECRET=your-32-char-secret-here
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

## 11. Updating

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
