# Agent / Node Connection Guide

This document explains how an autonomous agent or worker node connects to the
AI Relay cluster and starts receiving tasks. For the full step-by-step guide see
**[docs/node/setup.md](docs/node/setup.md)**. For concepts and architecture see
**[docs/concepts.md](docs/concepts.md)**.

## 1. What is a node?

A **node** is any worker that registers with the relay, announces its
capabilities, and claims tasks. Nodes can be Python scripts, containers,
remote workers, or agents like this one.

## 2. Server address

Pick the address that matches where your agent is running:

- **Same machine as the relay:** `http://127.0.0.1:8788`
- **Another host on your Tailscale / local network:** use the relay host's
  Tailscale or LAN IP, e.g. `http://100.64.0.1:8788`

Always include the path prefix shown below. Do **not** register against the
dashboard HTML pages; use the API endpoints.

## 3. Register or reuse a token

### 3.1 Worker / service node

Worker nodes do **not** choose their own ID. The cluster assigns an 8-character
node ID when registration succeeds (see `docs/concepts.md`).

```http
POST /relay/v2/auth/register
Content-Type: application/json

{
  "node_name": "My first agent",
  "endpoint": "http://192.168.1.50:7777",
  "capabilities": [
    {"name": "chat.ai", "version": "1.0.0"}
  ]
}
```

The server returns three important values:

1. `node_id` — the 8-character ID the cluster assigned to you (e.g. `V34ETT74`).
2. `registration_secret` (`rs_...`) — recovery credential used to obtain a
   fresh runtime token.
3. `token` (`tp_...`) — a temporary token. It is **not** used for heartbeats or
   work; keep it only as a fallback.

Save `node_id` and `registration_secret`. An admin must approve the node in the
dashboard before it can claim work.

### 3.2 Admin / dashboard node

Admin nodes use the master bootstrap secret and the dedicated registration
endpoint:

```http
POST /relay/v2/auth/register-admin
Content-Type: application/json

{
  "node_name": "My admin client",
  "bootstrap_secret": "<master-seed>",
  "capabilities": [
    {"name": "admin", "version": "1.0.0"}
  ]
}
```

The master seed is intended for bootstrap and recovery only. During normal
operation a human administrator should use a regular dashboard account, or an
admin node should use its runtime token.

> **Tip:** Save the returned runtime token to a file (e.g.
> `~/.relay/ai-relay-agent.token`). On restart, reuse it instead of registering
> again.

## 4. Poll approval status

Use the `node_id` returned at registration time for status polling and
heartbeats. While pending, poll **without** an `Authorization` header:

```http
POST /relay/v2/auth/status
Content-Type: application/json

{
  "node_id": "<assigned_node_id>",
  "registration_secret": "rs_..."
}
```

The response is read-only and reports the current status (`pending`,
`approved`, `online`, or `offline`). It never issues tokens.

Once approved, the admin receives the first runtime token (`rt_...`). Save it to
`~/.relay/ai-relay-agent.token` and use it for **all** later calls (heartbeat,
claim, complete).

## 5. Refresh and recover credentials

### Refresh a runtime token before expiry

Runtime tokens expire after the configured TTL (default 7 days). Refresh them
proactively:

```http
POST /relay/v2/auth/refresh
Authorization: Bearer <current_rt_...>
Content-Type: application/json

{
  "requested_credential": "runtime_token"
}
```

The old runtime token is invalidated. Save the new token immediately.

### Recover a lost runtime token

If the runtime token was lost, use the registration secret:

```http
POST /relay/v2/auth/refresh
Content-Type: application/json

{
  "node_id": "<assigned_node_id>",
  "registration_secret": "rs_...",
  "requested_credential": "runtime_token"
}
```

The response contains a new runtime token **and a new registration secret**.
Persist both immediately.

## 6. Send heartbeats

A node must prove it is alive. Send a heartbeat every few seconds:

```http
POST /relay/v2/discovery/heartbeat
Authorization: Bearer <rt_...>
Content-Type: application/json

{
  "available": true,
  "load": 0.0,
  "queue_depth": 0,
  "capabilities": [{"name": "chat.ai", "version": "1.0.0"}]
}
```

Recommended interval: **8 seconds**. Server timeout is 5 × heartbeat interval.

After the first heartbeat an `approved` node moves to `online`. Runtime tokens
stay valid for both states. A node that misses too many heartbeats is marked
`offline`.

## 7. Claim tasks

Once approved and online, claim available work:

```http
POST /relay/v2/scheduler/claim
Authorization: Bearer <rt_...>
Content-Type: application/json

{
  "capability": "chat.ai"
}
```

If a stage is available, the response contains the stage details. Execute the
work, then complete the stage:

```http
POST /relay/v2/scheduler/stages/{stage_id}/complete
Authorization: Bearer <rt_...>
Content-Type: application/json

{
  "node_id": "<assigned_node_id>",
  "task_id": "<task_id>",
  "result": {"status": "ok", "answer": "..."}
}
```

## 8. Capabilities

Common capability names you can register:

| Capability | Typical execution mode | Meaning |
|------------|------------------------|---------|
| `chat` | `.ai` | General conversational agent work |
| `code` | `.ai` | Coding, review, and debugging |
| `web` | `.ai` | Web search and extraction |
| `vision` | `.ai` | Image analysis |
| `terminal` | `.native` or `.ai` | Shell execution |
| `file` | `.native` | Filesystem operations |

A capability name such as `chat` without a suffix is a category. A concrete
execution offer uses a suffix that describes the mode, for example `chat.ai`
(local AI handles the request) or `chat.native` (direct rule-based execution).
The relay matches capability names exactly: a stage asking for `chat.ai` will
only be claimed by a node that currently advertises `chat.ai`.

You can invent your own capability names when the core names do not fit, but
tasks must reference exactly those names.

## 9. Example node code

Look at `examples/agent-integration/ai-relay-agent-poller.py` in this
repository for a KI-capable agent that delegates work to the local Hermes AI.
For a generic base class see `nodes/common/poller.py`.