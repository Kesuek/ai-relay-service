# AI Relay — Node Registration and Token Concept

This document explains how nodes authenticate with the AI Relay Service, which
tokens exist, and how the registration/approval flow works.

## 1. Actors

| Actor | What it is | Needs a token? |
|-------|------------|----------------|
| **Relay server** | Central task router | No (it validates tokens) |
| **Master admin** | Emergency bootstrap/recovery credential | Uses `adm_...` seed |
| **Human admin** | Day-to-day dashboard user | Uses signed session cookie |
| **Admin node** | Dashboard, CLI admin tools, or orchestrator | Uses `rt_...` runtime token |
| **Worker node** | General AI agent | Uses `rt_...` runtime token |
| **Service node** | KI-less worker (storage, printer, etc.) | Uses `rt_...` runtime token |

## 2. Secret and token types

The relay uses four different secret/token families. Their prefixes make them
easy to distinguish.

| Prefix | Name | Purpose | Lifetime |
|--------|------|---------|----------|
|| `adm_...` | **Master admin seed** | Bootstrap the cluster and recover admin access | Until rotated |
|| `hu_...`  | **Human user password** | Dashboard login for human users | Until changed |
|| `rs_...` | **Registration secret** | Recovery credential used only to recover a runtime token | 12 hours |
|| `tp_...` | **Temporary token** | Short-lived token returned immediately after registration; used only until approval | 24 hours by default |
|| `rt_...` | **Runtime token** | Bearer token for all node operations: heartbeat, claim, complete | 7 days by default |

> **Important:** The master admin seed is equivalent to root access, but it is
> only usable when no human admin exists or when recovery mode is explicitly
> enabled. Store it in a password manager. Never commit it.

## 3. Bootstrap: creating the master admin seed and first human admin

Before any node can authenticate, the cluster needs a master admin seed. This is
done once, **on the relay host itself**, using the CLI command:

```bash
relay-server admin init-master
```

Response (printed once):

```text
adm_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
Store it securely. It will not be shown again.
```

The server stores only a bcrypt hash of this seed. The plain seed is never kept
on disk. If you lose it, you must reset the database.

> **Security note:** The master seed is created only through the command line.
> The HTTP API intentionally has no endpoint to initialize it. This prevents an
> network attacker from claiming the cluster root key before the legitimate
> administrator.

### 3.1 First human admin

After the master seed is created, start the server and open the dashboard.
Because no human admin exists yet, the login form shows the **Master seed**
option. Log in with the seed and use the bootstrap page to create the first
human admin. The dashboard generates a temporary password that must be changed
on first login. Once that is done, master-seed login is automatically disabled
until recovery mode is enabled.


## 4. Registering a node

### 4.1 Worker or service node

A node registers without any prior secret:

```http
POST /relay/v2/auth/register
Content-Type: application/json

{
  "node_name": "nas-storage-01",
  "endpoint": null,
  "capabilities": [
    {"name": "storage.archive", "version": "1.0.0"}
  ],
  "role": "service"
}
```

The relay returns:

```json
{
  "node_id": "V34ETT74",
  "node_name": "nas-storage-01",
  "status": "pending",
  "token_type": "temporary",
  "token": "tp_...",
  "expires_at": "2026-06-22T14:00:00+00:00",
  "registration_secret": "rs_..."
}
```

Save three values:

1. `node_id` — used for status polling and heartbeats
2. `registration_secret` — long-lived secret for refreshing tokens
3. `token` — temporary, only useful until approval

The node is now **pending** and cannot claim work.

### 4.2 Admin node

An admin node is created directly with a runtime token, using the master admin
seed:

```http
POST /relay/v2/auth/register-admin
Content-Type: application/json

{
  "node_name": "Dashboard Admin",
  "bootstrap_secret": "adm_...",
  "capabilities": [
    {"name": "admin", "version": "1.0.0"}
  ]
}
```

Response:

```json
{
  "node_id": "A1B2C3D4",
  "node_name": "Dashboard Admin",
  "status": "approved",
  "token_type": "runtime",
  "token": "rt_...",
  "expires_at": "2026-06-28T14:00:00+00:00"
}
```

## 5. Approval

A worker or service node must be approved by an admin before it can work.

### Using the dashboard

1. Open `http://ai-relay.local:8788/relay/v2/dashboard/`
2. Log in with a human admin account
3. Find the pending node and click **Approve**
4. Confirm the role and capabilities

> The master seed can only be used for dashboard login while no human admin
> exists or when recovery mode is enabled. For normal operation, create a
> human admin during bootstrap and use that account.

### Using the API

```bash
curl -H "Authorization: Bearer rt_..." \
  -X POST \
  http://ai-relay.local:8788/relay/v2/admin/nodes/V34ETT74/approve \
  -d '{
    "role": "service",
    "capabilities": [
      {"name": "storage.archive", "version": "1.0.0"},
      {"name": "storage.list", "version": "1.0.0"},
      {"name": "storage.delete", "version": "1.0.0"}
    ]
  }'
```

Response:

```json
{
  "node_id": "V34ETT74",
  "status": "approved",
  "token_type": "runtime",
  "token": "rt_...",
  "expires_at": "2026-06-28T14:00:00+00:00"
}
```

Approval:
- Moves the node from `pending` to `approved`
- Invalidates the temporary token
- Creates a runtime token for the node

## 6. Runtime token recovery

After approval the worker receives its first runtime token via the admin
approval response. The worker should immediately call `POST /relay/v2/auth/refresh`
with its runtime token and `requested_credential: "registration_secret"` to
obtain the current registration secret, and persist both credentials.

If the worker loses its runtime token, the registration secret can be used to
recover a new one:

```http
POST /relay/v2/auth/refresh
Content-Type: application/json

{
  "node_id": "V34ETT74",
  "registration_secret": "rs_...",
  "requested_credential": "runtime_token"
}
```

The response contains a new runtime token. The previous runtime token (if any)
is invalidated.

## 7. Credential status

The worker can check how long its credentials remain valid without changing
anything:

```http
POST /relay/v2/auth/status
Authorization: Bearer ***
Content-Type: application/json

{
  "node_id": "V34ETT74"
}
```

Response:

```json
{
  "node_id": "V34ETT74",
  "node_name": "nas-storage-01",
  "status": "approved",
  "rt_valid_until": "2026-06-30T03:41:23+00:00",
  "rs_valid_until": "2026-06-23T15:41:23+00:00",
  "message": "Credential status"
}
```

This endpoint is read-only and does not rotate credentials. The worker should
poll it every few hours and refresh credentials proactively before they expire.

## 7. Runtime token usage

The runtime token is a Bearer token. It is used for all authenticated requests:

```http
POST /relay/v2/discovery/heartbeat
Authorization: Bearer rt_...
Content-Type: application/json

{
  "node_id": "V34ETT74",
  "status": "online"
}
```

```http
POST /relay/v2/scheduler/claim
Authorization: Bearer rt_...
Content-Type: application/json

{
  "capability": "storage.archive"
}
```

## 8. Token lifetime and refresh

| Token | Default lifetime | Refreshable? |
|-------|------------------|--------------|
| `adm_...` | Until rotated | No (it is a seed, not a token) |
| `hu_...` | Until changed | No (human dashboard password) |
| `rs_...` | Unlimited | No (used to refresh `rt_...`) |
| `tp_...` | 24 hours | No |
| `rt_...` | 7 days | Yes |

### Refresh a runtime token

```http
POST /relay/v2/auth/refresh
Authorization: Bearer rt_...
```

Response:

```json
{
  "node_id": "V34ETT74",
  "node_name": "nas-storage-01",
  "status": "approved",
  "token_type": "runtime",
  "token": "rt_...",
  "expires_at": "2026-06-28T14:00:00+00:00"
}
```

The old token is invalidated. Save the new token.

If the runtime token expires, the node can request a fresh one with the
registration secret via `/relay/v2/auth/status`.

## 9. What a node should persist

A node needs to survive restarts without re-registering. Persist these files:

| File | Content |
|------|---------|
| `~/.relay/ai-relay-agent.json` | `node_id`, `node_name`, `capabilities`, `registration_secret`, `relay_url` |
| `~/.relay/ai-relay-agent.token` | Current `rt_...` runtime token |

Example `ai-relay-agent.json`:

```json
{
  "node_id": "V34ETT74",
  "node_name": "nas-storage-01",
  "capabilities": [
    {"name": "storage.archive", "version": "1.0.0"}
  ],
  "registration_secret": "rs_...",
  "relay_url": "http://ai-relay.local:8788"
}
```

On startup:

1. If `ai-relay-agent.json` exists → load `node_id` and `registration_secret`
2. Use `/relay/v2/auth/status` with the registration secret to get a fresh
   runtime token
3. Save the new token to `~/.relay/ai-relay-agent.token`
4. If no registration file exists → register the node and save both secrets

The registration secret is the node's long-term identity. Never lose it.

## 10. Security model

### Threat: runtime token stolen

An attacker with a runtime token can act as that node until the token expires.
Mitigation: tokens expire, can be refreshed, and are invalidated on refresh.

### Threat: registration secret stolen

An attacker with the registration secret can poll for new runtime tokens.
Mitigation: keep `ai-relay-agent.json` in a protected directory. Rotate is
possible only by deleting and re-registering the node.

### Threat: master seed stolen

An attacker with the master seed can create admin tokens and approve arbitrary
nodes. Mitigation: store it in a password manager; never write it to disk on a
node; rotate by resetting the relay database.

### Threat: temporary token intercepted

The temporary token is short-lived and becomes invalid after approval.
Mitigation: approve nodes quickly; do not use the temporary token for heartbeats
or work.

## 11. Token summary diagram

```
Admin / human
     │
     │ relay-server admin init-master
     ▼
 ┌─────────────┐
 │  adm_...    │  master seed (one-time)
 └──────┬──────┘
        │
        │ used to register admin node
        ▼
 ┌─────────────┐
 │   rt_...    │  admin runtime token
 └──────┬──────┘
        │
        │ approves pending node
        ▼
 ┌─────────────┐          ┌─────────────┐
 │   rs_...    │──────────│   tp_...    │  registration secret + temporary token
 │             │          │             │
 │   rt_...    │◄─────────│   status    │  runtime token after approval
 └─────────────┘          └─────────────┘
```

## 12. Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `401 Unauthorized` | Token expired or invalid | Refresh the token via `/relay/v2/auth/refresh` or request a new one with the registration secret |
| `403 Forbidden` | Node is still pending | Approve the node in the dashboard or via admin API |
| Lost `rs_...` | Cannot refresh runtime tokens | Delete the node entry and re-register |
| Lost `adm_...` | Cannot create admin nodes | Reset the relay database and re-bootstrap via `relay-server admin init-master` |

## 12. Quick command reference

```bash
# Initialize master seed (must be run on the relay host)
relay-server admin init-master

# Register a service node
curl -X POST http://${RELAY_HOST}:8788/relay/v2/auth/register \
  -H "Content-Type: application/json" \
  -d '{"node_name":"nas-storage-01","capabilities":[{"name":"storage.archive","version":"1.0.0"}]}'

# Poll for approval
curl -X POST http://ai-relay.local:8788/relay/v2/auth/status \
  -H "Content-Type: application/json" \
  -d '{"node_id":"V34ETT74","registration_secret":"rs_..."}'

# Refresh runtime token
curl -X POST http://ai-relay.local:8788/relay/v2/auth/refresh \
  -H "Authorization: Bearer rt_..."

# Approve node (admin only)
curl -X POST http://ai-relay.local:8788/relay/v2/admin/nodes/V34ETT74/approve \
  -H "Authorization: Bearer rt_..." \
  -H "Content-Type: application/json" \
  -d '{"role":"service","capabilities":[{"name":"storage.archive","version":"1.0.0"}]}'
```
