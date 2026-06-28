# Worker-Node Setup — Proxmox LXC

This guide describes how to set up an AI-Relay worker node inside a Proxmox VE
LXC container. The node runs the generic `node-cli` daemon (heartbeat + claim
loop) and connects to an already-running relay server.

## Prerequisites

- Proxmox VE server (tested with v8.x / v9.x)
- A Debian 12 LXC template available in Proxmox
- The relay server is already running and reachable from the container
  (see [../setup.md](../setup.md))
- You know the relay URL (e.g. `http://192.168.2.10:8788` or
  `http://ai-relay.local:8788`)

## 1. Create the container

In the Proxmox Web UI (or via `pct`):

- **Template:** Debian 12 (`debian-12-standard`)
- **Unprivileged:** OFF (use a **privileged** container, `unprivileged=0`).
  `python-keyring` and systemd user sessions require `keyctl`, which is not
  available inside unprivileged containers by default. Alternatively use an
  unprivileged container with `keyctl=1` in the config.
- **Resources:** 2 CPU cores, 1–2 GB RAM, 10 GB rootfs
- **Network:** static IP, e.g. `192.168.2.50/24`, gateway `192.168.2.1`

```bash
# On the Proxmox host (example: CTID 110)
pct create 110 debian-12-standard \
  --hostname ai-relay-worker \
  --cores 2 --memory 2048 --rootfs local-lvm:10 \
  --net0 name=eth0,bridge=vmbr0,ip=192.168.2.50/24,gw=192.168.2.1 \
  --unprivileged 0
pct start 110
pct enter 110
```

## 2. Base setup inside the container

```bash
apt update && apt -y upgrade
apt -y install python3 python3-venv python3-pip git sudo curl jq
# (optional) a non-root user
adduser felix && usermod -aG sudo felix
```

Python 3.11+ is required (`python3 --version`). Debian 12 ships 3.11.

## 3. Install the worker node code

Worker nodes are **not** installed via `pip install -e .`. Clone the repo and
run the node modules directly:

```bash
sudo -u felix bash
cd ~
git clone https://github.com/felix/ai-relay-service.git
cd ai-relay-service
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"      # server deps (httpx, pyyaml, pydantic) reused
```

> The `node-cli` console script was removed from the server package. Start the
> daemon via `python -m nodes.common.node_cli`.

## 4. Define capabilities

Create a capability profile for the worker:

```bash
mkdir -p ~/.relay/capabilities.d
cat > ~/.relay/capabilities.d/default.yaml <<'YAML'
capabilities:
  - name: chat.ai
    version: "1.0.0"
    auto_publish: true
    claimable: true
    handler: /opt/relay/handlers/chat-ai.sh
    max_parallel: 2
    timeout: 300
YAML

# Validate and publish (daemon reads only capabilities.active.yaml)
python -m nodes.common.node_cli capabilities validate default
python -m nodes.common.node_cli capabilities publish default
```

See [capabilities.md](capabilities.md) for the full profile format and handler
contract.

## 5. Register the node

```bash
curl -X POST "http://${RELAY_HOST}:8788/relay/v2/auth/register" \
  -H "Content-Type: application/json" \
  -d '{
    "node_name": "proxmox-worker-1",
    "endpoint": null,
    "role": "worker",
    "capabilities": [{"name": "chat.ai", "version": "1.0.0"}]
  }' | tee /tmp/register.json
```

Save the credentials into the state file:

```bash
mkdir -p ~/.relay
jq '{node_id, node_name, registration_secret, capabilities, base_url: "http://'${RELAY_HOST}':8788"}' \
  /tmp/register.json > ~/.relay/ai-relay-agent.json
```

The node is now `pending` — wait for the admin to approve it (see
[../admin/setup.md](../admin/setup.md)). After approval, recover the runtime
token with the registration secret:

```bash
python -m nodes.common.node_cli heartbeat   # first heartbeat fails with 401 → recover
# or explicitly:
curl -X POST "http://${RELAY_HOST}:8788/relay/v2/auth/refresh" \
  -H "Content-Type: application/json" \
  -d "$(jq -c '{node_id, registration_secret, requested_credential: \"runtime_token\"}' ~/.relay/ai-relay-agent.json)" \
  | tee /tmp/refresh.json
jq -r .token /tmp/refresh.json > ~/.relay/ai-relay-agent.token
```

## 6. Start the daemon

### Foreground (test)

```bash
cd ~/ai-relay-service && source .venv/bin/activate
python -m nodes.common.node_cli daemon foreground
```

Check `~/.relay/worker_status.json` — a fresh heartbeat means the node is
`online`.

### systemd service

Create `/etc/systemd/system/ai-relay-worker.service`:

```ini
[Unit]
Description=AI Relay Worker Node
After=network-online.target

[Service]
Type=simple
User=felix
WorkingDirectory=/home/felix/ai-relay-service
Environment=RELAY_BASE_URL=http://192.168.2.10:8788
ExecStart=/home/felix/ai-relay-service/.venv/bin/python -m nodes.common.node_cli daemon foreground
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ai-relay-worker.service
systemctl status ai-relay-worker.service
```

## 7. Verify

- `python -m nodes.common.node_cli status` shows the last heartbeat.
- In the relay dashboard the node appears as `online`.
- Submit a matching task — the worker claims and completes the stage.

## 8. Troubleshooting

| Problem | Solution |
|---|---|
| `401` on heartbeat | Runtime token expired or missing → refresh via `/auth/refresh`. |
| `403` on claim | Capability not in the latest heartbeat → check `capabilities.active.yaml`. |
| `404` on `/auth/refresh` | Middleware force-password-change or wrong path — confirm `RELAY_BASE_URL`. |
| Node stays `pending` | Admin has not approved it yet (dashboard → Nodes → Approve). |
| Node `offline` in dashboard | Daemon not running, or heartbeat interval too long. Check `systemctl status`. |
| `keyctl` / keyring errors | Container is unprivileged without `keyctl=1` — switch to privileged or add `keyctl=1` to the CT config. |
| Both credentials expired | Re-register the node (see [../node-readme.md](../node-readme.md) §2). |

## Next steps

- **[token-lifecycle.md](token-lifecycle.md)** — refresh & recovery details
- **[capabilities.md](capabilities.md)** — handler contract & profile rules
- **[../node-readme.md](../node-readme.md)** — full node connection guide
