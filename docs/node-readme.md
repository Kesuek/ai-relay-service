# AI Relay — Node Connection Guide

This document is written from the perspective of a node that wants to join an AI
Relay cluster. It explains what a node must do to connect, register, wait for
activation, and keep working.

## 1. What you need before starting

A node needs one piece of information: the relay URL.

Examples:

- `http://192.168.1.50:8788`
- `http://ai-relay.local:8788` (if your network supports mDNS)

If you do not know the URL, ask the person who installed the relay. The relay
administrator can find it on the relay host or in the dashboard.

## 2. Register once

Send a registration request for each capability you provide:

```bash
curl -X POST "http://${RELAY_HOST}:8788/relay/v2/auth/register" \
  -H "Content-Type: application/json" \
  -d '{
    "node_name": "my-node",
    "endpoint": "http://192.168.1.60:9000",
    "role": "service",
    "capabilities": [
      {"name": "chat", "version": "1.0.0"}
    ]
  }'
```

Save the response:

```json
{
  "node_id": "V34ETT74",
  "node_name": "my-node",
  "status": "pending",
  "token_type": "temporary",
  "token": "tp_...",
  "expires_at": "2026-06-28T14:00:00+00:00",
  "registration_secret": "rs_..."
}
```

Store these values persistently:

- `node_id` — your unique ID in the cluster
- `registration_secret` — used to poll for approval and refresh tokens
- `~/.relay/ai-relay-agent.json` — common location

The temporary token is only valid for 24 hours, but the registration secret
stays valid until the node is approved.

## 3. Wait for activation

A newly registered node is in `pending` state. It cannot claim work yet. The
node should poll `/relay/v2/auth/status` until the relay administrator
activates it.

```bash
curl -X POST "http://${RELAY_HOST}:8788/relay/v2/auth/status" \
  -H "Content-Type: application/json" \
  -d '{
    "node_id": "V34ETT74",
    "registration_secret": "rs_..."
  }'
```

While waiting:

```json
{
  "node_id": "V34ETT74",
  "status": "pending",
  "message": "Awaiting admin activation"
}
```

After activation:

```json
{
  "node_id": "V34ETT74",
  "status": "approved",
  "token": "rt_...",
  "token_type": "runtime",
  "expires_at": "2026-06-28T14:00:00+00:00",
  "message": "Node approved — runtime token issued"
}
```

Save the runtime token to `~/.relay/ai-relay-agent.token`.

> The relay administrator activates nodes in the dashboard or with an admin
> script. A node cannot approve itself.

## 4. Keep the node alive

Once activated, send a heartbeat every few seconds. The recommended interval is
**8 seconds**.

```bash
curl -X POST "http://${RELAY_HOST}:8788/relay/v2/discovery/heartbeat" \
  -H "Authorization: Bearer ${RUNTIME_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "node_id": "V34ETT74",
    "status": "online",
    "load": 0.0,
    "queue_depth": 0
  }'
```

A node that misses too many heartbeats is considered offline and will not
receive tasks.

## 5. Claim work

With a valid runtime token, a node can claim a stage that matches one of its
capabilities:

```bash
curl -X POST "http://${RELAY_HOST}:8788/relay/v2/scheduler/claim" \
  -H "Authorization: Bearer ${RUNTIME_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "capability": "chat"
  }'
```

If work is available, the relay returns a stage:

```json
{
  "stage_id": "stg_...",
  "task_id": "tsk_...",
  "stage_name": "answer",
  "capability": "chat",
  "payload": {
    "question": "What is the current time in Tokyo?"
  }
}
```

If nothing matches, the response is empty. The node should poll again after a
short delay (1–3 seconds).

## 6. Complete or fail a stage

After finishing the work, report the result:

```bash
curl -X POST "http://${RELAY_HOST}:8788/relay/v2/scheduler/complete" \
  -H "Authorization: Bearer ${RUNTIME_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "stage_id": "stg_...",
    "status": "completed",
    "result": {"answer": "It is 21:45 in Tokyo."}
  }'
```

If the work fails:

```bash
curl -X POST "http://${RELAY_HOST}:8788/relay/v2/scheduler/complete" \
  -H "Authorization: Bearer ${RUNTIME_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "stage_id": "stg_...",
    "status": "failed",
    "result": {"error": "Model not available"}
  }'
```

## 7. Refresh the runtime token

Runtime tokens expire after the configured TTL (default 7 days). Before expiry,
refresh the token:

```bash
curl -X POST "http://${RELAY_HOST}:8788/relay/v2/auth/refresh" \
  -H "Authorization: Bearer ${RUNTIME_TOKEN}"
```

Save the new token immediately. The old token becomes invalid.

If the token already expired, use the registration secret to request a new
runtime token through `/relay/v2/auth/status`.

## 8. Service nodes and self-care

KI-less service nodes are not allowed to make AI decisions. When they encounter
something ambiguous, they post a decision task back to the relay instead of
guessing.

Example: a storage node receives a stage to archive a file, but the target path
is missing. It posts a decision task with capability `chat` or `decision` so a
KI-capable node can answer. After the decision is resolved, the service node
continues.

See `nodes-design.md` for the full self-care pattern.

## 9. Helper scripts and examples

| Path | Purpose |
|------|---------|
| `examples/nodes/node_base.py` | Base class that handles registration, heartbeat, claim, and complete loops |
| `examples/nodes/relay_client.py` | HTTP client for the relay API |
| `nodes/storage-node/poller.py` | Generic poller for KI-less service nodes |
| `nodes/storage-node/register.py` | One-time registration for the storage node |
| `scripts/manual_node_test.py` | Manual end-to-end node test |

## 10. Checklist for a new node

- [ ] Know the relay URL from configuration or the user
- [ ] Register via `/relay/v2/auth/register`
- [ ] Save `node_id` and `registration_secret` to `~/.relay/ai-relay-agent.json`
- [ ] Wait until the relay administrator activates the node
- [ ] Poll `/relay/v2/auth/status` to receive the `rt_...` runtime token
- [ ] Save the runtime token to `~/.relay/ai-relay-agent.token`
- [ ] Start sending heartbeats every 8 seconds
- [ ] Start the claim → work → complete loop
- [ ] Refresh the runtime token before it expires

## 11. Common mistakes

| Mistake | Consequence | Fix |
|---------|-------------|-----|
| Forgetting heartbeats | Node marked offline | Send heartbeats every 8 seconds |
| Losing the registration secret | Cannot refresh tokens | Keep `ai-relay-agent.json` safe |
| Claiming with the wrong capability | No tasks received | Use one of the registered capabilities |
| Node stays pending forever | Nobody activated it | Ask the relay administrator to activate it |
| Runtime token expired | All authenticated requests fail | Use `/relay/v2/auth/status` with the registration secret to get a new one |

## 12. Relay administrator tasks

The following actions are **not** performed by a node. They are done by the
human or KI agent that operates the relay:

- Install and start the relay server
- Create the master admin seed
- Activate pending nodes in the dashboard
- Issue new runtime tokens when needed
- Delete nodes from the cluster

For these tasks, the administrator should read `setup.md` and `dashboard.md`.

## 13. Next steps

- For understanding tokens, see `token-concept.md`.
- For node design patterns, see `nodes-design.md`.
- For installing and configuring the relay, see `setup.md`.
- For managing users and approving nodes, see `dashboard.md`.
