# AI Relay — Node README

This document is written from the perspective of a node that wants to join an AI
Relay cluster. It explains what a node must do: find the relay, register, wait
for approval, and keep itself alive.

## 1. What is a node?

A node is any program that connects to the AI Relay and performs work. Nodes
can be:

- **KI nodes** — agents that reason, plan, generate content, or talk to users
- **Service nodes** — dumb workers that execute raw actions like storing files,
  toggling switches, running backups, or printing documents

Every node registers with the relay, advertises one or more **capabilities**,
and claims matching tasks.

## 2. Find the relay server

The relay is usually available as `http://ai-relay.local:8788` if mDNS is
enabled on the relay host. If mDNS does not work in your network, use the relay
host's static IP.

### Try mDNS first

```bash
ping -c 1 ai-relay.local
```

If it resolves, use `http://ai-relay.local:8788`.

### Fallback to IP

Ask the user or scan the local network. Common relay IPs in this environment:

- `http://192.168.2.170:8788`

Update the node configuration or environment variable:

```bash
export RELAY_BASE_URL=http://192.168.2.170:8788
```

## 3. Register the node

A node registers by calling `/relay/v2/auth/register`. It does not choose its
own ID; the relay assigns an 8-character node ID.

```http
POST /relay/v2/auth/register
Content-Type: application/json

{
  "node_name": "my-node",
  "endpoint": null,
  "capabilities": [
    {"name": "chat", "version": "1.0.0"}
  ],
  "role": "worker"
}
```

The relay returns:

```json
{
  "node_id": "V34ETT74",
  "status": "pending",
  "token_type": "temporary",
  "token": "tp_...",
  "expires_at": "2026-06-22T14:00:00+00:00",
  "registration_secret": "rs_..."
}
```

Save these values to a persistent file, for example:

```json
{
  "node_id": "V34ETT74",
  "node_name": "my-node",
  "registration_secret": "rs_...",
  "relay_url": "http://ai-relay.local:8788",
  "capabilities": [
    {"name": "chat", "version": "1.0.0"}
  ]
}
```

### Important files

| File | Purpose |
|------|---------|
| `~/.relay/ai-relay-agent.json` | Long-lived node identity: `node_id`, `registration_secret`, capabilities |
| `~/.relay/ai-relay-agent.token` | Current runtime token (`rt_...`) |

Do not lose the `registration_secret`. It is the only way to get fresh runtime
tokens without re-registering.

## 4. Wait for approval

A newly registered node is in `pending` state. It cannot claim work yet. The node
should poll `/relay/v2/auth/status` until an admin approves it.

```http
POST /relay/v2/auth/status
Content-Type: application/json

{
  "node_id": "V34ETT74",
  "registration_secret": "rs_..."
}
```

While pending:

```json
{
  "node_id": "V34ETT74",
  "status": "pending",
  "message": "Awaiting admin approval"
}
```

After approval:

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

Save the runtime token and start the main loop.

If the node restarts, use the registration secret to request a fresh runtime
token via `/relay/v2/auth/status`.

## 5. Keep the node alive

Once approved, send a heartbeat every few seconds. The recommended interval is
**8 seconds**.

```http
POST /relay/v2/discovery/heartbeat
Authorization: Bearer rt_......ype: application/json

{
  "node_id": "V34ETT74",
  "status": "online",
  "load": 0.0,
  "queue_depth": 0
}
```

A node that misses too many heartbeats is considered offline and will not
receive tasks.

## 6. Claim and execute work

Ask the relay for work matching a capability:

```http
POST /relay/v2/scheduler/claim
Authorization: Bearer rt_......ype: application/json

{
  "capability": "chat"
}
```

If work is available, the relay returns a stage:

```json
{
  "stage_id": "stg_...",
  "task_id": "tsk_...",
  "stage_name": "answer",
  "capability": "chat",
  "payload": {
    "question": "What is the weather in Leipzig?"
  }
}
```

Execute the work and report the result:

```http
POST /relay/v2/scheduler/stages/stg_.../complete
Authorization: Bearer rt_......ype: application/json

{
  "node_id": "V34ETT74",
  "task_id": "tsk_...",
  "result": {
    "status": "ok",
    "answer": "22°C and sunny in Leipzig."
  }
}
```

## 7. Refresh the runtime token

Runtime tokens expire. Refresh them before they expire:

```http
POST /relay/v2/auth/refresh
Authorization: Bearer rt_...
```

Response:

```json
{
  "node_id": "V34ETT74",
  "token_type": "runtime",
  "token": "rt_...",
  "expires_at": "2026-06-28T14:00:00+00:00"
}
```

Save the new token. If the token expires, request a fresh one with the
registration secret via `/relay/v2/auth/status`.

## 8. Helper scripts

This repository contains helper scripts and examples for nodes.

| Path | Use case |
|------|----------|
| `examples/nodes/node_base.py` | Base class that handles registration, heartbeat, claim, and complete loops |
| `examples/nodes/relay_client.py` | HTTP client for the relay API |
| `examples/nodes/approve_nodes.py` | Admin script to approve pending nodes |
| `nodes/storage-node/poller.py` | Generic poller for KI-less service nodes |
| `nodes/storage-node/register.py` | One-time registration for the storage node |
| `scripts/manual_node_test.py` | Manual end-to-end node test |

Use `examples/nodes/node_base.py` as a starting point for new nodes. It handles
the lifecycle automatically.

## 9. Minimal node checklist

Before a node can work, it must:

- [ ] Know the relay URL (`http://ai-relay.local:8788` or IP)
- [ ] Register via `/relay/v2/auth/register`
- [ ] Save `node_id` and `registration_secret` to `~/.relay/ai-relay-agent.json`
- [ ] Wait for an admin to approve the node
- [ ] Poll `/relay/v2/auth/status` to receive the `rt_...` runtime token
- [ ] Save the runtime token to `~/.relay/ai-relay-agent.token`
- [ ] Start sending heartbeats every 8 seconds
- [ ] Start claiming tasks for advertised capabilities
- [ ] Refresh the runtime token before it expires

## 10. Service nodes: ask for help

Service nodes are intentionally dumb. They execute only what the stage says.

If a service node detects a situation that requires a decision, it must **not**
decide on its own. Instead, it posts a decision task back to the relay:

```json
{
  "task_name": "storage.decide_cleanup",
  "stages": [
    {
      "stage_name": "decide",
      "capability": "llm.decide_cleanup",
      "payload": {
        "usage_ratio": 0.91,
        "candidates": ["2026/01/old_image.png"]
      }
    }
  ]
}
```

A KI node will claim the decision stage and return instructions.

## 11. Common mistakes

| Mistake | Result | Fix |
|---------|--------|-----|
| Using the temporary token for heartbeats | `401 Unauthorized` | Wait for approval and use the runtime token |
| Forgetting heartbeats | Node marked offline | Send heartbeats every 8 seconds |
| Losing the registration secret | Cannot refresh tokens | Keep `ai-relay-agent.json` safe |
| Claiming with the wrong capability | No tasks received | Use one of the registered capabilities |
| Node stays pending forever | No admin approved it | Ask an admin to approve the node |

## 12. Quick command reference

```bash
# Register node
curl -X POST http://ai-relay.local:8788/relay/v2/auth/register \
  -H "Content-Type: application/json" \
  -d '{"node_name":"my-node","capabilities":[{"name":"chat","version":"1.0.0"}]}'

# Check approval status
curl -X POST http://ai-relay.local:8788/relay/v2/auth/status \
  -H "Content-Type: application/json" \
  -d '{"node_id":"V34ETT74","registration_secret":"rs_..."}'

# Send heartbeat
curl -X POST http://ai-relay.local:8788/relay/v2/discovery/heartbeat \
  -H "Authorization: Bearer rt_... \
  -H "Content-Type: application/json" \
  -d '{"node_id":"V34ETT74","status":"online","load":0.0}'

# Claim task
curl -X POST http://ai-relay.local:8788/relay/v2/scheduler/claim \
  -H "Authorization: Bearer rt_... \
  -H "Content-Type: application/json" \
  -d '{"capability":"chat"}'

# Refresh token
curl -X POST http://ai-relay.local:8788/relay/v2/auth/refresh \
  -H "Authorization: Bearer rt_...
```
