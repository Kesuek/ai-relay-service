# Admin Guide

Tasks performed by the human or KI agent that **operates the relay**. Nodes do
not perform these actions.

For the server installation itself see [setup.md](setup.md). For the dashboard
UI see [dashboard.md](dashboard.md). For the credential concept see
[../concepts.md](../concepts.md).

## Install & run the server

The full server installation, bootstrap, recovery, and systemd setup is in
**[setup.md](setup.md)**. Quick reference:

```bash
git clone https://github.com/Kesuek/ai-relay-service.git
cd ai-relay-service
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
relay-server admin init-master     # save the adm_... secret
relay-server server --port 8788
```

## Bootstrap the first human admin

1. Open `http://<relay>:8788/relay/v2/dashboard/`
2. Choose **Master seed** and paste the seed from `init-master`
3. Enter a username for the first admin
4. Store the generated temporary password, log out, log in again
5. Change the temporary password when prompted

After that, master-seed login is automatically disabled.

## Recovery mode

If all human admins are locked out, enable recovery from the relay host.
Recovery re-activates master-seed login so the master seed can bootstrap a
new admin.

```bash
# 1. Disable every human admin account (required).
relay-recovery --db-path ~/.relay/server.db enable-recovery --all

# 2. Restart the relay with master-seed login allowed.
RELAY_ENABLE_MASTER_SEED_LOGIN=true relay-server server --port 8788
```

Now the dashboard login form shows the **Master seed** option again. Use it
to create a new human admin and change the temporary password.

### What `--all` does and why it is required

`enable-recovery --all` flips the `active` flag to `0` on **every** human
admin account in the database. The relay refuses to start with
`RELAY_ENABLE_MASTER_SEED_LOGIN=true` unless **all** human admins are
disabled — this prevents an attacker who stole the master seed from
silently hijacking a running cluster. As long as a single human admin is
still active, master-seed login stays blocked.

### Turning recovery off

Once the new admin exists and has changed the temporary password:

1. Stop the relay.
2. Restart it **without** `RELAY_ENABLE_MASTER_SEED_LOGIN` (set the env var
   to `false` or drop it, and ensure `enable_master_seed_login: false` in
   `config.yaml`).
3. Re-activate the legitimately needed admin accounts through the dashboard
   (the new admin you just created can do this).

Master-seed login is now unavailable again until the next explicit
recovery.

## Manage nodes

Every new node starts in `pending` state and must be activated before it can
claim work. See [../node/setup.md](../node/setup.md) for the node side of the
flow.

### Approve a node (dashboard)

1. Open **Nodes** in the dashboard
2. Find the pending node → **Approve**
3. Review role and capabilities → **Confirm**

### Approve a node (API)

Register an admin node with the master seed, then approve:

```bash
ADMIN_TOKEN=$(curl -s -X POST "http://<relay>:8788/relay/v2/auth/register-admin" \
  -H "Content-Type: application/json" \
  -d "{\"node_name\":\"admin-cli\",\"bootstrap_secret\":\"${ADM_SECRET}\",\"endpoint\":null,\"capabilities\":[{\"name\":\"admin\",\"version\":\"1.0.0\"}]}" \
  | jq -r .token)

curl -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -X POST "http://<relay>:8788/relay/v2/admin/nodes/${NODE_ID}/approve" \
  -H "Content-Type: application/json" \
  -d '{"role":"service","capabilities":[{"name":"storage.archive.native","version":"1.0.0"}]}'
```

### Issue a new runtime token

When a node lost its token or it expired before refresh:

```bash
curl -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -X POST "http://<relay>:8788/relay/v2/admin/nodes/${NODE_ID}/token"
```

This invalidates the previous runtime token for that node.

### Delete a node

Removes records, tokens, presence data, and task claims:

```bash
curl -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -X DELETE "http://<relay>:8788/relay/v2/admin/nodes/${NODE_ID}"
```

## Node status values

| Status | Meaning | Set by |
|---|---|---|
| `pending` | Registered, not yet approved | Relay on registration |
| `approved` | Approved, no heartbeat yet | Relay on approval |
| `online` | Sent at least one heartbeat | Relay on heartbeat |
| `offline` | Missed too many heartbeats | Relay watchdog |

`available`, `load`, `queue_depth` in the heartbeat control whether the
scheduler actually sends more work; `online` + `available=false` means
"alive but do not send tasks right now".

## Security notes

- The master seed (`adm_...`) is equivalent to root access. Store it securely.
- Runtime tokens (`rt_...`) live in `~/.relay/` by default.
- Never commit tokens or the master seed to git.
- Keep the relay behind your firewall; it is designed for private networks.
- Master-seed login is unavailable during normal operation — enable recovery
  mode first if every admin is locked out.

## Next steps

- [dashboard.md](dashboard.md) — dashboard UI guide
- [../node/setup.md](../node/setup.md) — node connection guide
- [../node/token-lifecycle.md](../node/token-lifecycle.md) — token refresh and recovery
- [../reference/api.md](../reference/api.md) — full API endpoint table