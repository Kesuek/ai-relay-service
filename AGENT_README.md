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

Every node needs a runtime token. The first time a node runs it registers itself:

```http
POST /relay/v2/discovery/register
Content-Type: application/json

{
  "node_id": "my-agent-01",
  "node_name": "My first agent",
  "endpoint": "http://192.168.1.50:7777",
  "capabilities": [
    {"name": "chat", "version": "1.0"}
  ]
}
```

The server returns a `pending` token. An admin must approve the node in the dashboard before it can claim work.

> **Tip:** Save the returned token to a file (e.g. `~/.relay/my-agent-01.token`). On restart, reuse it instead of registering again.

## 4. Send heartbeats

A node must prove it is alive. Send a heartbeat every few seconds:

```http
POST /relay/v2/discovery/heartbeat
Authorization: Bearer <token>
Content-Type: application/json

{
  "node_id": "my-agent-01",
  "status": "online",
  "load": 0.0,
  "queue_depth": 0
}
```

Recommended interval: **8 seconds**. Server timeout is 5 × heartbeat interval.

## 5. Claim tasks

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

## 6. Capabilities

Common capability names you can register:

- `chat` — general conversational agent work
- `code` — coding / terminal / file work
- `web` — web search and extraction
- `vision` — image analysis

You can invent your own capability names; tasks must then reference exactly those names.

## 7. Example node code

Look at `examples/nodes/node_base.py` in this repository for a ready-to-use base class that handles registration, heartbeat, claim and complete loops.

## 8. HTML guide

A browser-readable version of this guide is available at:

```
http://127.0.0.1:8788/relay/v2/dashboard/agent-readme
```

Linked from the login page for convenience.
