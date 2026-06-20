# Agent / Node Connection Guide

This document explains how an autonomous agent or worker node connects to the AI Relay cluster and starts receiving tasks.

## 1. What is a node?

A **node** is any worker that registers with the relay, announces its capabilities, and claims tasks. Nodes can be Python scripts, containers, remote workers, or agents like this one.

## 2. Server address

Pick the address that matches where your agent is running:

- **Same machine as the relay:** `http://127.0.0.1:8788`
- **Another host on your Tailscale / local network:** use the relay host's Tailscale or LAN IP, e.g. `http://100.64.0.1:8788`

Always include the path prefix shown below. Do **not** register against the dashboard HTML pages; use the API endpoints.

## 3. Register or reuse a token

### 3.1 Worker / service node

Worker nodes do **not** choose their own ID. The cluster assigns an 8-character ADR-001 node ID when registration succeeds.

```http
POST /relay/v2/auth/register
Content-Type: application/json

{
  "node_name": "My first agent",
  "endpoint": "http://192.168.1.50:7777",
  "capabilities": [
    {"name": "chat", "version": "1.0"}
  ]
}
```

The server returns three important values:

1. `node_id` — the 8-character ID the cluster assigned to you (e.g. `V34ETT74`).
2. `registration_secret` (`rs_...`) — the key you need to poll for your final runtime token.
3. `token` (`tp_...`) — a temporary token. It is **not** used for heartbeats or work; keep it only as a fallback.

Save all three, especially the `node_id` and `registration_secret`. An admin must approve the node in the dashboard before it can claim work.

### 3.2 Admin / dashboard node

Admin nodes use the master bootstrap secret and the dedicated registration endpoint:

```http
POST /relay/v2/auth/register-admin
Content-Type: application/json

{
  "node_name": "My admin client",
  "bootstrap_secret": "<master-seed>",
  "capabilities": [
    {"name": "admin", "version": "1.0"}
  ]
}
```

> **Tip:** Save the returned runtime token to a file (e.g. `~/.relay/<assigned_node_id>.token`). On restart, reuse it instead of registering again.

## 4. Poll approval status

Use the `node_id` returned at registration time for status polling and heartbeats.

```http
POST /relay/v2/auth/status
Content-Type: application/json

{
  "node_id": "<assigned_node_id>",
  "registration_secret": "rs_..."
}
```

Once approved, the response contains the `rt_...` runtime token. This is the token you use for **all** later calls (heartbeat, claim, complete). Save it as `~/.relay/<node_id>.token` and reuse it on restart.

If you lose the runtime token, you can request a fresh one with the same `/relay/v2/auth/status` call as long as you still have the `node_id` and `registration_secret`.

## 5. Send heartbeats

A node must prove it is alive. Send a heartbeat every few seconds:

```http
POST /relay/v2/discovery/heartbeat
Authorization: Bearer ***
Content-Type: application/json

{
  "node_id": "<assigned_node_id>",
  "status": "online",
  "load": 0.0,
  "queue_depth": 0
}
```

Recommended interval: **8 seconds**. Server timeout is 5 × heartbeat interval.

## 6. Claim tasks

Once approved and online, claim available work:

```http
POST /relay/v2/scheduler/claim
Authorization: Bearer ***
Content-Type: application/json

{
  "capability": "chat"
}
```

If a stage is available, the response contains the stage details. Execute the work, then complete the stage:

```http
POST /relay/v2/scheduler/stages/{stage_id}/complete
Authorization: Bearer ***
Content-Type: application/json

{
  "node_id": "<assigned_node_id>",
  "task_id": "<task_id>",
  "result": {"status": "ok", "answer": "..."}
}
```

## 7. Capabilities

Common capability names you can register:

- `chat` — general conversational agent work
- `code` — coding / terminal / file work
- `web` — web search and extraction
- `vision` — image analysis

You can invent your own capability names; tasks must then reference exactly those names.

## 8. Example node code

Look at `examples/nodes/node_base.py` in this repository for a ready-to-use base class that handles registration, heartbeat, claim and complete loops.
