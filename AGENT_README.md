# Agent / Node Connection Guide

This document explains how an autonomous agent or worker node connects to the AI Relay cluster and starts receiving tasks.

## 1. What is a node?

A **node** is any worker that registers with the relay, announces its capabilities, and claims tasks. Nodes can be Python scripts, containers, remote workers, or autonomous agents.

## 2. Server address

The relay server runs on:

```
http://127.0.0.1:8788
```

Dashboard for humans:

```
http://127.0.0.1:8788/dashboard
http://127.0.0.1:8788/dashboard/login
```

## 3. Register or reuse a token

Every node needs a runtime token. The first time a node runs it registers itself.

### 3.1 Worker / service node

Worker nodes do **not** choose their own ID; the cluster assigns an 8-character ADR-001 node ID when registration succeeds.

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

The server returns:

- a temporary token (`tp_...`),
- a `registration_secret` (`rs_...`),
- status `pending`.

Save both. The registration secret is used to poll for approval; the temporary token lets you send heartbeats while pending.

## 4. Poll approval status

While pending, call:

```http
POST /relay/v2/auth/status
Content-Type: application/json

{
  "node_id": "<assigned_node_id>",
  "registration_secret": "rs_..."
}
```

Response while pending:

```json
{
  "node_id": "<assigned_node_id>",
  "node_name": "My first agent",
  "status": "pending",
  "message": "Awaiting admin approval"
}
```

Response once approved:

```json
{
  "node_id": "<assigned_node_id>",
  "node_name": "My first agent",
  "status": "approved",
  "token": "rt_...",
  "token_type": "runtime",
  "expires_at": "2026-06-21T...",
  "message": "Node approved — use this runtime token"
}
```

Save the `rt_...` runtime token and use it for all further API calls. Poll `/relay/v2/auth/status` every few seconds until approved.

## 5. Send heartbeats

A node must prove it is alive. Send a heartbeat every few seconds:

```http
POST /relay/v2/discovery/heartbeat
Authorization: Bearer <token>
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
Authorization: Bearer <token>
Content-Type: application/json

{
  "capability": "chat"
}
```

If a stage is available, the response contains the stage details. Execute the work, then complete the stage:

```http
POST /relay/v2/scheduler/complete
Authorization: Bearer <token>
Content-Type: application/json

{
  "stage_id": "stage_...",
  "task_id": "task_...",
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

## 9. HTML guide

A browser-readable version of this guide is available at:

```
http://127.0.0.1:8788/relay/v2/dashboard/agent-readme
```

Linked from the login page for convenience.
