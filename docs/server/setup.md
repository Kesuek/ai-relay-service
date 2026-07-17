# AI Relay Service — Server Setup

This guide explains how to install, configure, and run the AI Relay Service
core on your host. Node setup is documented separately in
[node/setup.md](../node/setup.md).

## What you get

- A central relay server that routes tasks between nodes
- A web dashboard at `http://ai-relay.local:8788/relay/v2/dashboard/`
- Optional mDNS advertisement so nodes can find the relay as `ai-relay.local`

For the architecture and concepts behind the relay see
[../concepts.md](../concepts.md).

## Requirements

- Linux host for the relay (a small server, NAS, or always-on PC)
- Python 3.11+ to run the relay from source
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
> recovery mode is explicitly enabled. See [admin.md](admin.md) for the
> bootstrap and recovery flow.

## 4. Start the relay server

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

## 5. Bootstrap the first human admin

When the server starts for the first time, no human admin exists. The dashboard
login form therefore shows the **Master seed** option.

1. Open `http://ai-relay.local:8788/relay/v2/dashboard/`
2. Choose **Master seed** and paste the seed from step 3
3. You are redirected to the bootstrap page
4. Enter a username (and optional email) for the first admin
5. Store the generated temporary password securely
6. Log out and log in again as the new admin
7. You are forced to change the password before you can use the dashboard

After that, master-seed login is automatically disabled. For day-to-day work,
always use human admin accounts.

See [dashboard.md](dashboard.md) for the full dashboard guide.

## 6. Recovery mode

If all human admin accounts are locked out, enable recovery from the relay host:

```bash
relay-recovery --db-path ~/.relay/server.db enable-recovery --all
```

Then restart the server with recovery mode enabled:

```bash
RELAY_ENABLE_MASTER_SEED_LOGIN=true relay-server server --port 8788
```

Now the master seed can log in again and bootstrap a new admin. Once a new
admin exists and has changed the temporary password, recovery mode is no
longer needed and should be turned off. See [admin.md](admin.md) for details.

## 7. Approve nodes

Every new node starts in `pending` state. An administrator must activate it
before it can claim work. Nodes are activated in the dashboard or via the admin
API — see [admin.md](admin.md) and [dashboard.md](dashboard.md).

## 8. Verify the setup

```bash
curl http://ai-relay.local:8788/health
```

## 9. Systemd service for the relay

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

## 10. Updating

Pull the latest code, reinstall, and restart:

```bash
cd ai-relay-service
git pull
source .venv/bin/activate
pip install -e ".[dev]"
sudo systemctl restart ai-relay.service
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `ai-relay.local` not found | Use the relay's IP address directly |
| mDNS blocks startup | Update to the latest relay-server version; mDNS now starts asynchronously |
| Port 8788 already in use | Stop the old relay process first |
| Node stays pending | Approve it in the dashboard or via admin API (see [admin.md](admin.md)) |

## Security notes

- The master seed (`adm_...`) is equivalent to root access. Store it securely.
- Runtime tokens (`rt_...`) are stored in `~/.relay/` by default.
- Do not commit tokens or the master seed to git.
- Keep the relay behind your firewall; it is designed for private networks.

## Next steps

- [admin.md](admin.md) — node management and admin API
- [dashboard.md](dashboard.md) — dashboard usage
- [../node/setup.md](../node/setup.md) — connect a node
- [../concepts.md](../concepts.md) — architecture and concepts