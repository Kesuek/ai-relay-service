# Node Setup — From Zero to Daemon

This guide takes a node from a blank host to a running, online daemon that
claims and completes tasks on the relay. It is **platform-independent**; a
short Proxmox LXC example appears at the end.

The guide assumes the relay server is already running and reachable. See
[../server/setup.md](../server/setup.md) for the server side. For the concepts
behind nodes, capabilities, and tokens see [../concepts.md](../concepts.md).

## Prerequisites

- The relay URL (e.g. `http://192.168.2.10:8788` or `http://ai-relay.local:8788`)
- Python 3.11+
- Network access to the relay

## 1. Install the node code

Nodes are **not** installed via `pip install -e .` for the server. Clone the
repo and run the node modules directly:

```bash
git clone https://github.com/Kesuek/ai-relay-service.git
cd ai-relay-service
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"      # server deps reused (httpx, pyyaml, pydantic)
```

> **Note on the `node-cli` command:** the `node-cli` console script was
> removed from the server package and is **no longer installed**. Always
> invoke the CLI via its module path:
>
> ```bash
> python -m nodes.common.node_cli <command> [options]
> ```
>
> The examples in this guide use the shorthand `node-cli` for readability —
> read it as `python -m nodes.common.node_cli`. If you want a real
> `node-cli` command in your shell, add an alias or a tiny wrapper:
>
> ```bash
> # ~/.bashrc or ~/.zshrc
> alias node-cli='python -m nodes.common.node_cli'
> # or, a wrapper on $PATH that works everywhere (incl. systemd):
> echo 'exec python -m nodes.common.node_cli "$@"' | sudo tee /usr/local/bin/node-cli && sudo chmod +x /usr/local/bin/node-cli
> ```

## 2. Register the node

Register once against the relay:

```bash
curl -X POST "http://${RELAY_HOST}:8788/relay/v2/auth/register" \
  -H "Content-Type: application/json" \
  -d '{
    "node_name": "my-node",
    "endpoint": null,
    "role": "service",
    "capabilities": [{"name": "chat.ai", "version": "1.0.0"}]
  }' | tee /tmp/register.json
```

Save the response — it contains your `node_id`, a temporary token (`tp_…`,
24 h), and a `registration_secret` (`rs_…`, 12 h):

```json
{
  "node_id": "V34ETT74",
  "status": "pending",
  "token": "tp_...",
  "registration_secret": "rs_..."
}
```

## 3. Persist the state file

Persist the response in `~/.relay/ai-relay-agent.json`. The runtime token lives
separately in `~/.relay/ai-relay-agent.token` so it can be rotated without
rewriting the state file.

```bash
mkdir -p ~/.relay
jq '{node_id, node_name, registration_secret, capabilities, base_url: "http://'${RELAY_HOST}':8788"}' \
  /tmp/register.json > ~/.relay/ai-relay-agent.json
```

State file schema:

```json
{
  "node_id": "V34ETT74",
  "node_name": "my-node",
  "endpoint": "http://192.168.1.60:9000",
  "registration_secret": "rs_...",
  "capabilities": [{"name": "chat.ai", "version": "1.0.0"}],
  "base_url": "http://192.168.1.50:8788"
}
```

## 4. Wait for approval

The node is now `pending` and cannot claim work. An admin must activate it
in the dashboard or via the admin API (see [../server/admin.md](../server/admin.md)).
A node cannot approve itself.

Poll `/relay/v2/auth/status` **without** a Bearer token until the relay admin
activates the node:

```bash
curl -X POST "http://${RELAY_HOST}:8788/relay/v2/auth/status" \
  -H "Content-Type: application/json" \
  -d '{"node_id": "V34ETT74", "registration_secret": "rs_..."}'
```

```json
{ "node_id": "V34ETT74", "status": "pending", "message": "Awaiting admin activation" }
```

## 5. Obtain the runtime token

After approval, obtain a runtime token. The admin may provide it, or the node
recovers it with the registration secret:

```bash
curl -X POST "http://${RELAY_HOST}:8788/relay/v2/auth/refresh" \
  -H "Content-Type: application/json" \
  -d "$(jq -c '{node_id, registration_secret, requested_credential: \"runtime_token\"}' ~/.relay/ai-relay-agent.json)" \
  | tee /tmp/refresh.json
jq -r .token /tmp/refresh.json > ~/.relay/ai-relay-agent.token
# persist the rotated registration secret too
jq -r .registration_secret /tmp/refresh.json
```

See [token-lifecycle.md](token-lifecycle.md) for the full refresh and recovery
flow.

## 6. Define capability profiles

The `node-cli` daemon is **capability-agnostic**: all capabilities are defined
in external YAML profiles. The daemon reads only
`~/.relay/capabilities.active.yaml`; working profiles live in
`~/.relay/capabilities.d/`.

```bash
mkdir -p ~/.relay/capabilities.d
cat > ~/.relay/capabilities.d/default.yaml <<'YAML'
capabilities:
  - name: chat.ai
    version: "1.0.0"
    auto_publish: true          # include in every heartbeat
    claimable: true             # daemon may claim stages for this capability
    handler: /opt/relay/handlers/chat-ai.sh   # required when claimable: true
    max_parallel: 2            # in-flight handler limit (default: 1)
    timeout: 300                # handler timeout in seconds (default: 300)
YAML
```

Validate and publish (the daemon reads only `capabilities.active.yaml`):

```bash
python -m nodes.common.node_cli capabilities validate default
python -m nodes.common.node_cli capabilities publish default
```

See [capabilities.md](capabilities.md) for the full profile format and the
handler contract.

## 7. Start the daemon

### Foreground (test)

```bash
cd ~/ai-relay-service && source .venv/bin/activate
python -m nodes.common.node_cli daemon foreground
```

### Background

```bash
python -m nodes.common.node_cli daemon start
```

The daemon writes a PID file at `~/.relay/node-cli.pid` and a log file at
`~/.relay/node-cli.log`. It sends a heartbeat every 8 seconds by default and
claims stages for every `claimable` capability in the active profile.

### systemd service

Create `/etc/systemd/system/ai-relay-node.service`:

```ini
[Unit]
Description=AI Relay Node
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
sudo systemctl enable --now ai-relay-node.service
systemctl status ai-relay-node.service
```

## 8. Verify

- `python -m nodes.common.node_cli status` shows the last heartbeat.
- `~/.relay/worker_status.json` is written after every heartbeat.
- In the relay dashboard the node appears as `online`.
- Submit a matching task — the node claims and completes the stage.

```bash
curl http://${RELAY_HOST}:8788/health
python -m nodes.common.node_cli heartbeat
python -m nodes.common.node_cli status
```

## Checklist for a new node

- [ ] Know the relay URL
- [ ] Install the node code
- [ ] Register via `/relay/v2/auth/register`
- [ ] Save `node_id` and `registration_secret` to `~/.relay/ai-relay-agent.json`
- [ ] Wait until the admin activates the node (poll `/auth/status`)
- [ ] Obtain the runtime token → `~/.relay/ai-relay-agent.token`
- [ ] Define and publish a capability profile
- [ ] Start the daemon (foreground first, then systemd)
- [ ] Refresh tokens before expiry; recover with the registration secret if lost
- [ ] Configure a systemd unit, LaunchAgent, or container restart policy

## Token storage & permissions

The runtime token (`~/.relay/ai-relay-agent.token`) and state file
(`~/.relay/ai-relay-agent.json`) are credentials — anyone who can read them
can impersonate the node. The daemon **does not** set restrictive
permissions automatically. Secure them yourself:

```bash
chmod 600 ~/.relay/ai-relay-agent.token ~/.relay/ai-relay-agent.json
chmod 700 ~/.relay
ls -l ~/.relay/ai-relay-agent.token
# -rw------- ... ai-relay-agent.token
```

For a systemd service, enforce it in the unit:

```ini
[Service]
...
UMask=0077
# Or, if you manage the files out-of-band:
ExecStartPre=/bin/chmod 600 %h/.relay/ai-relay-agent.token %h/.relay/ai-relay-agent.json
```

Alternatives for containers / hosts where you do not want files on disk:

- **Bind-mount** a read-only token file from the host secret store into the
  container at `~/.relay/ai-relay-agent.token` (and the state file at
  `~/.relay/ai-relay-agent.json`).
- **Provision the files** at startup from a secret manager
  (e.g. `vault kv get -field=token … > ~/.relay/ai-relay-agent.token &&
  chmod 600 ~/.relay/ai-relay-agent.token`) in an `ExecStartPre=` or
  container entrypoint.

Never commit `~/.relay/ai-relay-agent.token` or `ai-relay-agent.json` to git
or include them in image layers.

> The node CLI currently reads the token **only** from
> `~/.relay/ai-relay-agent.token`; an env-var fallback
> (`RELAY_RUNTIME_TOKEN`) is referenced by the dashboard UI but not yet
> honoured by the CLI. Until it is, keep the token in the file.

## Troubleshooting

| Problem | Solution |
|---|---|
| `401` on heartbeat | Runtime token expired or missing → refresh via `/auth/refresh`. If lost, recover with the registration secret (see [token-lifecycle.md](token-lifecycle.md)). |
| `403` on claim | Capability not in the latest heartbeat → check `capabilities.active.yaml` and that `auto_publish: true`. |
| `404` on `/auth/refresh` | Wrong `RELAY_BASE_URL`, or the node was deleted by an admin → re-register. |
| Node stays `pending` | Admin has not approved it yet (dashboard → Nodes → Approve). |
| Node `offline` in dashboard | Daemon not running, or heartbeat interval too long. `systemctl status ai-relay-node.service` and `tail ~/.relay/node-cli.log`. |
| Both credentials expired | Re-register the node (step 2). |
| `ConnectionError` / `Network is unreachable` | Check `RELAY_BASE_URL`, reachability (`curl http://<relay>:8788/health`), and firewall on both ends. |
| `python: command not found` / wrong version | Use `python3` explicitly; require 3.11+ (`python3 --version`). Install via `pyenv` or your distro's `python3.11` package. |
| `Permission denied: ~/.relay/...` | The user running the daemon must own `~/.relay/`. `chown -R $USER ~/.relay`, `chmod 700 ~/.relay`. |
| Daemon exits immediately under systemd | Use absolute paths in `ExecStart` (`.venv/bin/python`), set `WorkingDirectory`, and `User=` to the owner of `~/.relay`. Check `journalctl -u ai-relay-node`. |
| Daemon starts but won't claim | No `claimable: true` capability, or `handler` path missing/executable. `node-cli capabilities validate`. |
| Handler `timeout` in results | Raise the `timeout:` field in the profile, or make the handler faster. |
| mDNS name unreachable from the node | Use the IP address in `RELAY_BASE_URL`, or enable an mDNS reflector on the router. |

## Example: Proxmox LXC

A minimal Proxmox VE container setup for a worker node.

```bash
# On the Proxmox host (CTID 110)
pct create 110 debian-12-standard \
  --hostname ai-relay-worker \
  --cores 2 --memory 2048 --rootfs local-lvm:10 \
  --net0 name=eth0,bridge=vmbr0,ip=192.168.2.50/24,gw=192.168.2.1 \
  --unprivileged 0          # privileged: python-keyring needs keyctl
pct start 110
pct enter 110

# Inside the container
apt update && apt -y install python3 python3-venv python3-pip git sudo curl jq
adduser felix && usermod -aG sudo felix
sudo -u felix bash
cd ~
git clone https://github.com/Kesuek/ai-relay-service.git
cd ai-relay-service
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
# then continue with step 2 of this guide (register, approve, daemon)
```

> If you must use an unprivileged container, add `keyctl=1` to the CT config so
> `python-keyring` and systemd user sessions work.

## Next steps

- [token-lifecycle.md](token-lifecycle.md) — token types, refresh, recovery
- [capabilities.md](capabilities.md) — capability formats and `node-cli` profiles
- [cli-reference.md](cli-reference.md) — full `node-cli` command reference
- [../server/admin.md](../server/admin.md) — node approval from the admin side
- [../concepts.md](../concepts.md) — architecture and self-care pattern