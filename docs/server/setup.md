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

### Option B: Run with Docker (not yet available)

> The repository does **not** currently include a relay-server Dockerfile or a
> published image. Docker support is planned. Until then use **Option A**
> (install from source) or write your own `Dockerfile` starting from
> `python:3.11-slim` and `pip install -e .`. A community Docker setup is
> welcome — open a PR.

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

## 9. HTTPS / TLS

The relay core speaks **plain HTTP** only. It has no built-in TLS. Terminate
TLS in a reverse proxy in front of it — this keeps the core small and lets
you use standard tooling for certificate management.

Recommended setup:

```
Internet / LAN  ──HTTPS──▶  Reverse proxy (TLS)  ──HTTP──▶  relay :8788
```

### Caddy (recommended — automatic Let's Encrypt)

```caddyfile
# /etc/caddy/Caddyfile
ai-relay.example.com {
    reverse_proxy 127.0.0.1:8788
}
```

Caddy obtains and renews the certificate automatically. Reload with
`systemctl reload caddy`.

### nginx

```nginx
# /etc/nginx/sites-available/ai-relay
server {
    listen 443 ssl http2;
    server_name ai-relay.example.com;

    ssl_certificate     /etc/letsencrypt/live/ai-relay.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/ai-relay.example.com/privkey.pem;

    client_max_body_size 110m;   # > max_upload_bytes (100 MiB) + multipart overhead

    location / {
        proxy_pass http://127.0.0.1:8788;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto https;

        # SSE: disable buffering, allow long-lived streams
        proxy_buffering off;
        proxy_read_timeout 24h;
    }
}
```

Obtain the cert with `certbot --nginx -d ai-relay.example.com`.

### Traefik

```yaml
# /etc/traefik/traefik.yml
entryPoints:
  web:    { address: ":80"  }
  websecure: { address: ":443" }
certificatesResolvers:
  le: { acme: { email: you@example.com, storage: /etc/traefik/acme.json, httpChallenge: { entryPoint: web } } }
http:
  routers:
    ai-relay:
      rule: "Host(`ai-relay.example.com`)"
      service: ai-relay
      tls: { certResolver: le }
  services:
    ai-relay:
      loadBalancer: { servers: [ { url: "http://127.0.0.1:8788" } ] }
```

### Notes

- For LAN-only deployments without a DNS name, use a **self-signed** cert or
  keep plain HTTP on a trusted network. The relay is designed for private
  networks.
- When you proxy, set the dashboard session cookie to "secure" — the relay
  already sets `session_cookie_secure: true` by default, so it only sends
  the cookie over HTTPS. If you must run plain HTTP on a trusted LAN, set
  `session_cookie_secure: false` in `config.yaml`.
- Increase the proxy body limit above `max_upload_bytes` (default 100 MiB);
  otherwise large artifact uploads will be rejected by the proxy before they
  reach the relay.
- The SSE event stream (`GET /relay/v2/events/stream`) needs
  `proxy_buffering off` and a long read timeout, otherwise proxies buffer
  events and the stream appears dead.

## 10. Database

The relay uses **SQLite with WAL mode** as its sole database. No external
database server is required.

| Item | Value |
|---|---|
| Engine | SQLite 3 + WAL |
| Default path | `~/.relay/server.db` |
| Migrations | Automatic, additive, run on startup — no downtime, no manual steps |
| PostgreSQL | **Not supported.** The relay is a single-server design; Postgres is a future option |

### Backups

The database is a single file. Back it up with either:

```bash
# Cold copy (stop the relay first for a fully consistent snapshot)
systemctl stop ai-relay.service
cp ~/.relay/server.db ~/.relay/backup/server-$(date +%F).db
systemctl start ai-relay.service

# Hot backup (online, transaction-consistent)
sqlite3 ~/.relay/server.db ".backup ~/.relay/backup/server-$(date +%F).db"
```

WAL mode allows the hot backup to run while the relay is serving requests.
Schedule it with cron:

```cron
0 3 * * *  sqlite3 /home/felix/.relay/server.db ".backup /home/felix/.relay/backup/server-$(date +\%F).db"
```

### Recovery from a corrupt DB

If `server.db` ever becomes corrupt (very rare with WAL), restore the most
recent backup and restart the relay. The migration runner brings the schema
forward automatically.

## 11. Configuration reference

All settings can be set via environment variables (prefix `RELAY_`) or in
`~/.relay/config.yaml`. **YAML overrides env defaults.** Booleans use
`true`/`false`; paths accept `~` expansion.

```yaml
# ~/.relay/config.yaml — example with all common options
host: "0.0.0.0"
port: 8788
log_level: "info"            # debug | info | warning | error
enable_mdns: true
mdns_hostname: "ai-relay"

# Paths
db_path: "~/.relay/server.db"
artifacts_dir: "~/.relay/artifacts"
chunked_uploads_dir: "~/.relay/chunked_uploads"
# static_dir: null           # bundled static assets by default

# Auth / tokens
token_ttl_hours: 168                  # runtime token TTL (7 days)
registration_secret_ttl_hours: 12
temporary_token_ttl_hours: 24
claim_ttl_seconds: 60                 # how long a stage can stay "claimed"
heartbeat_interval_seconds: 10
heartbeat_timeout_multiplier: 5       # offline after 5 missed heartbeats

# Dashboard session
session_secret: "<random 32+ char string>"
session_cookie_secure: true           # set false only for plain-HTTP LAN
enable_master_seed_login: false       # enable only for recovery (see admin.md)

# Storage limits
max_upload_bytes: 104857600           # 100 MiB — single upload
max_payload_bytes: 10485760           # 10 MiB  — task payload
max_chunk_size: 10485760              # 10 MiB  — per chunked-upload chunk

# Scheduler
default_timeout_seconds: 300
max_retries: 2
```

The same keys can be set as `RELAY_PORT`, `RELAY_ENABLE_MDNS`,
`RELAY_SESSION_SECRET`, `RELAY_DB_PATH`, `RELAY_MAX_UPLOAD_BYTES`, etc.
Environment variables are read first; `config.yaml` overrides them; explicit
CLI flags (e.g. `--port`) override everything.

### Session secret rotation

The `session_secret` signs dashboard session cookies. To rotate it:

1. Generate a new secret: `openssl rand -base64 32`.
2. Put it in `~/.relay/config.yaml` (`session_secret:`) or
   `RELAY_SESSION_SECRET`.
3. Restart the relay: `systemctl restart ai-relay.service`.

**All existing dashboard sessions become invalid immediately** — every admin
has to log in again. Rotate only on suspicion of compromise, or during a
planned credential refresh. The secret is a persistent key otherwise: keep
it stable.

### Token lifecycle (nodes)

Runtime tokens (`rt_…`) expire after **7 days** by default. Nodes refresh
them automatically via `/relay/v2/auth/refresh` before expiry, and recover
with the registration secret if the runtime token was lost. You normally do
not need to do anything. Full flow in
[node/token-lifecycle.md](../node/token-lifecycle.md).

## 12. Performance & scaling

The relay is designed for **single-server, small-to-medium clusters**: tens
of nodes and hundreds of tasks per minute. SQLite with WAL handles this
comfortably — concurrent reads are non-blocking and writes are serialised
through the single writer, which is more than enough at this scale.

| Metric | Ballpark |
|---|---|
| Nodes | comfortable up to ~100 |
| Tasks/min | thousands on modest hardware |
| DB size | tens of MiB for years of metadata |

For larger deployments (hundreds of nodes, very high throughput), consider
running the relay on a dedicated host with an SSD, and sharding by
capability namespace. PostgreSQL support is **not yet implemented** but is
the planned upgrade path — the schema is deliberately simple to port.

There is no horizontal scaling story yet: one relay process owns the SQLite
file. Do not put a load balancer in front of multiple relay instances
pointing at the same `server.db`.

## 13. Systemd service for the relay

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

## 14. Updating

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
| `ai-relay.local` not found | Use the relay's IP address directly, or check that mDNS reflector is enabled on your router / Avahi is running on the relay host. |
| mDNS blocks startup | Update to the latest relay-server version; mDNS now starts asynchronously. |
| Port 8788 already in use | `ss -lntp \| grep 8788` to find the process, stop it, then restart. |
| Node stays `pending` | Approve it in the dashboard or via admin API (see [admin.md](admin.md)). |
| `database is locked` | Rare with WAL. Another relay process is likely running on the same `server.db` — stop duplicates. If it persists, restart the relay. |
| `OperationalError: no such table` | A migration did not run. Stop the relay, back up `server.db`, then restart so the migration runner fires. |
| Server refuses to start: "session_secret required" | Set `session_secret` in `~/.relay/config.yaml` or `RELAY_SESSION_SECRET` (see §2 / §11). |
| `permission denied` on `~/.relay/server.db` | The systemd `User=` must own `~/.relay/`. `chown -R felix:felix ~/.relay`. |
| Disk full under `~/.relay/` | Artifacts and the DB live here. Move `artifacts_dir` to a larger mount in `config.yaml`, then restart. |
| `pip install -e .` fails | Activate the venv first (`source .venv/bin/activate`); ensure build tools are present (`python3-dev`, `build-essential`). |
| venv not picked up by systemd | Use absolute paths in `ExecStart` (`/home/felix/.../.venv/bin/relay-server`), not `relay-server` from `$PATH`. |
| Firewall blocks nodes | Open port 8788 (TCP) on the relay host (`ufw allow 8788` / firewalld). mDNS needs UDP 5353 if you advertise `.local`. |
| `413 Request Entity Too Large` from the proxy | Raise the proxy body limit above `max_upload_bytes` (100 MiB default) — see §9. |
| SSE events never arrive through the proxy | Disable proxy buffering and raise the read timeout for the events path — see §9. |

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