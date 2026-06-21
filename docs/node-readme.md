# AI Relay — Node README

This document is written from the perspective of a node that wants to join an AI
Relay cluster. It explains what a node must do: discover or be told the relay
address, register, wait for approval, and keep itself alive.

## 1. What is a node?

A node is any program that connects to the AI Relay and performs work. Nodes can
be:

- **KI nodes** — agents that reason, plan, generate content, or talk to users
- **Service nodes** — dumb workers that execute raw actions like storing files,
  toggling switches, running backups, or printing documents

Every node registers with the relay, advertises one or more **capabilities**,
and claims matching tasks.

## 2. Configure the relay URL

Every node needs a relay URL. How the URL is determined depends on the
deployment:

- In a static network the relay host has a fixed IP such as
  `http://192.168.1.50:8788`.
- In a home or office network the relay may be advertised via mDNS as
  `http://ai-relay.local:8788`.
- Over a VPN such as Tailscale the address may look like `http://100.64.0.5:8788`.
- In cloud or container environments a DNS name or load balancer may be used.

Set the URL before starting the node:

```bash
export RELAY_BASE_URL=http://192.168.1.50:8788
```

If the node does not know the URL, it must ask the user or read it from its
configuration file. It should not assume mDNS is available.

Examples in this document use `http://${RELAY_HOST}:8788` as a placeholder.
Replace `${RELAY_HOST}` with the actual IP, hostname, or mDNS name of the relay.

## 3. Register the node

A node registers by calling `/relay/v2/auth/register`. It does not choose its
own ID; the relay assigns an 8-character node ID.

```bash
curl -X POST "http://${RELAY_HOST}:8788/relay/v2/auth/register" \
  -H "Content-Type: application/json" \
  -d '{
    "node_name": "my-node",
    "endpoint": null,
    "capabilities": [
      {"name": "chat", "version": "1.0.0"}
    ],
    "role": "worker"
  }'
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
  "relay_url": "http://192.168.1.50:8788",
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

```bash
curl -X POST "http://${RELAY_HOST}:8788/relay/v2/auth/status" \
  -H "Content-Type: application/json" \
  -d '{
    "node_id": "V34ETT74",
    "registration_secret": "rs_..."
  }'
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

## 6. Claim and execute work

Ask the relay for work matching a capability:

```bash
curl -X POST "http://${RELAY_HOST}:8788/relay/v2/scheduler/claim" \
  -H "Authorization: Bearer ${RUNTIME_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"capability": "chat"}'
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

Execute the work and report the result:

```bash
curl -X POST "http://${RELAY_HOST}:8788/relay/v2/scheduler/stages/${STAGE_ID}/complete" \
  -H "Authorization: Bearer ${RUNT...N}" \
  -H "Content-Type: application/json" \
  -d '{
    "node_id": "V34ETT74",
    "task_id": "tsk_...",
    "result": {
      "status": "ok",
      "answer": "The current time in Tokyo is 14:30 JST."
    }
  }'
```

## 7. Refresh the runtime token

Runtime tokens expire. Refresh them before they expire:

```bash
curl -X POST "http://${RELAY_HOST}:8788/relay/v2/auth/refresh" \
  -H "Authorization: Bearer ${RUNTIME_TOKEN}"
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

- [ ] Know the relay URL from configuration or the user
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

## 12. Further reading

- For a deeper explanation of node types, capabilities, and the self-care
  pattern, see `nodes-design.md`.
- For the full authentication and token model, see `token-concept.md`.
- For installing the relay server and a storage node, see `setup.md`.
