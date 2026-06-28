# Admin Guide

Tasks performed by the human or KI agent that **operates the relay**. Nodes
do not perform these actions.

## Install & run the server

The full server installation, bootstrap, recovery, systemd and storage-node
setup is in **[../setup.md](../setup.md)**. Quick reference:

```bash
git clone https://github.com/felix/ai-relay-service.git
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

If all human admins are locked out, enable recovery from the relay host:

```bash
relay-recovery enable-recovery --all
RELAY_ENABLE_MASTER_SEED_LOGIN=true relay-server server --port 8788
```

Once a new admin exists and has changed the password, turn recovery off.

## Manage nodes

Every new node starts in `pending` state and must be activated before it can
claim work.

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
