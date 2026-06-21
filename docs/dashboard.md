# AI Relay — Dashboard Guide

The AI Relay dashboard is a web interface for managing nodes, users, tasks, and
tokens. It is available at:

```
http://${RELAY_HOST}:8788/relay/v2/dashboard/
```

Replace `${RELAY_HOST}` with the relay IP, hostname, or mDNS name.

## 1. First login

Before any human user exists, the cluster must be bootstrapped with a master
admin seed. The master seed is the emergency root credential. It can only be
created from the command line on the relay host, never through the HTTP API.

### 1.1 Initialize the master seed (command line)

Log in to the relay host and run:

```bash
relay-server admin init-master
```

The command prints the seed once:

```text
adm_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

Store it in a password manager. It cannot be shown again.

### 1.2 Log in with the master seed

Open the dashboard login page and choose **Master seed**. Paste the seed and
sign in.

The master seed creates a special session that has all permissions. Use it only
for recovery or initial setup.

## 2. Human users

For daily administration, create human users with limited permissions. This is
safer than always using the master seed.

### 2.1 Create a user

In the dashboard, go to **Users → New user** and enter:

- Username (unique, no spaces)
- Password (stored as a bcrypt hash)
- Email (optional)
- Groups (default: `user`)

A user must be assigned to at least one group. Common groups:

| Group | Typical permissions |
|-------|---------------------|
| `admin` | Full access |
| `operator` | View dashboard, approve nodes |
| `readonly` | View only |

### 2.2 Groups and permissions

Permissions decide what a user can do in the dashboard:

| Permission | Allows |
|------------|--------|
| `dashboard:view` | View the dashboard and cluster overview |
| `nodes:approve` | Approve pending nodes |
| `nodes:token` | Issue new runtime tokens for approved nodes |
| `nodes:delete` | Delete nodes from the cluster |
| `users:manage` | Create, edit, and delete human users |
| `groups:manage` | Edit groups and their permissions |

To change permissions, go to **Groups**, select a group, and choose the
permissions for its members.

### 2.3 Activate, deactivate, or delete a user

- **Deactivate**: The user can no longer log in, but their history remains.
- **Delete**: Removes the user permanently.
- **Reset password**: Generates a new password for the user.

> You cannot delete the last active admin user. The master seed can always log
> in as a fallback.

## 3. Node management

The dashboard shows all registered nodes, their status, capabilities, and last
heartbeat.

### 3.1 Approve a pending node

When a node registers, it starts in `pending` state. Until it is approved, it
cannot claim work.

1. Open **Nodes**
2. Find the pending node in the list
3. Click **Approve**
4. Review or edit the role and capabilities
5. Click **Confirm**

The node receives a runtime token (`rt_...`) and can start claiming tasks.

### 3.2 Issue a new runtime token

If a node lost its token or the token expired, issue a new one:

1. Open **Nodes**
2. Find the approved node
3. Click **New token**
4. Copy the token and give it to the node, or save it to the node's
   `~/.relay/ai-relay-agent.token` file

Issuing a new token invalidates the previous runtime token for that node.

### 3.3 Delete a node

Deleting a node removes it completely from the cluster:

1. Open **Nodes**
2. Find the node
3. Click **Delete**
4. Confirm

This deletes:
- The node record
- All its runtime and temporary tokens
- Its presence data
- Claims and task ownership references

The node must register again if you want it back.

## 4. Cluster overview

The dashboard home page shows:

- Total nodes and online nodes
- Task statistics (pending, running, completed, failed)
- Active stages and which node claimed them
- Recent artifacts uploaded to the relay
- Recent events from the event bus

Click on a node, task, or artifact to see details.

## 5. Security best practices

### Master seed

- Store it in a password manager or hardware token
- Do not share it
- Do not write it into scripts or environment files on worker nodes
- If you suspect it was leaked, reset the relay database and bootstrap a new seed

### Human users

- Give each human their own user account
- Use groups instead of individual permissions
- Deactivate accounts that are no longer needed
- Reset passwords immediately after sharing them with a user

### Tokens

- Runtime tokens expire after 7 days by default
- If a token is leaked, issue a new one for the node
- Service nodes should store tokens in files with restricted permissions
  (`chmod 600 ~/.relay/ai-relay-agent.token`)

## 6. Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Cannot log in | Wrong username/password or expired master seed | Use the master seed to log in and reset the password |
| Pending node never becomes approved | No admin clicked Approve | Check **Nodes** and approve it manually |
| Node shows as offline | Heartbeats are missing | Restart the node and check its runtime token |
| User cannot approve nodes | Missing `nodes:approve` permission | Add the user to a group with that permission |
| Lost master seed | Not recoverable | Stop relay, delete the database file, and bootstrap again |

## 7. API endpoints used by the dashboard

The dashboard itself is a static HTML page that calls the following endpoints.
You can also use them from scripts or from KI nodes:

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/relay/v2/dashboard/login` | Login page |
| POST | `/relay/v2/dashboard/login` | Authenticate and set session cookie |
| POST | `/relay/v2/dashboard/logout` | Clear session |
| GET | `/relay/v2/dashboard/api/me` | Current user info |
| GET | `/relay/v2/dashboard/api/overview` | Cluster overview JSON |
| GET | `/relay/v2/dashboard/api/users` | List users |
| POST | `/relay/v2/dashboard/api/users` | Create user |
| POST | `/relay/v2/dashboard/api/users/{id}/password` | Reset password |
| POST | `/relay/v2/dashboard/api/users/{id}/active` | Activate/deactivate |
| DELETE | `/relay/v2/dashboard/api/users/{id}` | Delete user |
| GET | `/relay/v2/dashboard/api/groups` | List groups |
| GET | `/relay/v2/dashboard/api/permissions` | List permissions |
| POST | `/relay/v2/dashboard/api/groups/{id}/permissions` | Set group permissions |
| GET | `/relay/v2/admin/nodes` | List nodes |
| POST | `/relay/v2/admin/nodes/{id}/approve` | Approve node |
| POST | `/relay/v2/admin/nodes/{id}/token` | Issue new runtime token |
| DELETE | `/relay/v2/admin/nodes/{id}` | Delete node |

## 8. Example: approve a node from the command line

If you prefer scripts over the web UI, use the admin API:

```bash
MASTER_TOKEN="rt_..."  # runtime token of a dashboard/admin node
NODE_ID="V34ETT74"

curl -X POST "http://${RELAY_HOST}:8788/relay/v2/admin/nodes/${NODE_ID}/approve" \
  -H "Authorization: Bearer ${MASTER_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "role": "service",
    "capabilities": [
      {"name": "storage.archive", "version": "1.0.0"}
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

## 9. Example: issue a new token from the command line

```bash
curl -X POST "http://${RELAY_HOST}:8788/relay/v2/admin/nodes/${NODE_ID}/token" \
  -H "Authorization: Bearer ${MASTER_TOKEN}"
```

## 10. Example: delete a node from the command line

```bash
curl -X DELETE "http://${RELAY_HOST}:8788/relay/v2/admin/nodes/${NODE_ID}" \
  -H "Authorization: Bearer ${MASTER_TOKEN}"
```

## 11. Next steps

- For installing the relay server, see `setup.md`.
- For connecting a node, see `node-readme.md`.
- For understanding tokens, see `token-concept.md`.
- For node design patterns, see `nodes-design.md`.
