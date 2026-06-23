# AI Relay — Node Connection Guide

This document is written from the perspective of a node that wants to join an AI
Relay cluster. It explains how to connect, register, authenticate, claim work,
refresh credentials, and how other systems submit work that nodes can claim.

---

## 1. What you need before starting

A node needs one piece of information: the relay URL.

Examples:

- `http://192.168.1.50:8788`
- `http://ai-relay.local:8788` (if your network supports mDNS)

If you do not know the URL, ask the person who installed the relay.

---

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

Persist the response in `~/.relay/ai-relay-agent.json`. See the schema in
section 10.

The temporary token is only valid for 24 hours and is replaced by a runtime
token after the node is approved.

---

## 3. Node state file

The node state file is `~/.relay/ai-relay-agent.json`. It stores the data the
node needs to authenticate and refresh tokens.

```json
{
  "node_id": "V34ETT74",
  "node_name": "my-node",
  "endpoint": "http://192.168.1.60:9000",
  "registration_secret": "rs_...",
  "capabilities": [
    {"name": "chat", "version": "1.0.0"}
  ],
  "base_url": "http://192.168.1.50:8788"
}
```

The runtime token is stored separately in `~/.relay/ai-relay-agent.token` so it
can be rotated without rewriting the state file.

---

## 4. Wait for activation

A newly registered node is in `pending` state. It cannot claim work yet.
Poll `/relay/v2/auth/status` **without** a `Bearer` token until the relay
administrator activates the node.

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

After approval the admin receives a runtime token and may provide it to the
node, or the node can recover it with the registration secret (section 7).

### Read-only status check with the runtime token

Once the node owns a runtime token, it checks credential lifetimes like this:

```bash
curl -X POST "http://${RELAY_HOST}:8788/relay/v2/auth/status" \
  -H "Authorization: Bearer rt_..." \
  -H "Content-Type: application/json" \
  -d '{"node_id": "V34ETT74"}'
```

Response:

```json
{
  "node_id": "V34ETT74",
  "status": "approved",
  "rt_valid_until": "2026-06-30T03:41:23+00:00",
  "rs_valid_until": "2026-06-23T15:41:23+00:00",
  "message": "Credential status"
}
```

`/relay/v2/auth/status` is **read-only**. It never issues or rotates tokens.

> The relay administrator activates nodes in the dashboard or with an admin
> script. A node cannot approve itself.

---

## 5. Token lifecycle

```
[Register] → temporary token (24h) + registration secret (12h)
       ↓
[Admin approves] → runtime token (7 days), node status: approved
       ↓
[Heartbeat every 8s] → status becomes online → claim → work → complete
       ↓
[Before expiry] → POST /auth/refresh → new runtime token
       ↓
[Lost runtime token] → POST /auth/refresh with registration_secret
                       → new runtime token + new registration secret
       ↓
[Both credentials expired] → re-register
```

Only `/relay/v2/auth/refresh` creates or rotates credentials. `/auth/status`
only reports lifetimes. A recovery via registration secret rotates the
registration secret; persist the new one immediately.

---

## 6. Keep the node alive

Once activated, send a heartbeat every few seconds. The recommended interval is
**8 seconds**.

```bash
curl -X POST "http://${RELAY_HOST}:8788/relay/v2/discovery/heartbeat" \
  -H "Authorization: Bearer rt_..." \
  -H "Content-Type: application/json" \
  -d '{
    "available": true,
    "load": 0.0,
    "queue_depth": 0,
    "capabilities": [
      {"name": "chat", "version": "1.0.0"}
    ]
  }'
```

A node that misses too many heartbeats is considered offline and will not
receive tasks. Once the node sends a valid heartbeat again, the relay
automatically moves it back to `online`.

`endpoint` is set during registration (section 2). It does not need to be
sent again in the heartbeat body. If it changes, re-register or use the
dashboard.

Capabilities may be sent as objects or plain strings, and each heartbeat
updates the node's advertised capabilities. A node can change what it offers
at runtime by sending different capabilities in subsequent heartbeats:

```json
{ "capabilities": ["chat.ai", "code.ai"] }
```

The scheduler uses the most recent heartbeat capabilities for matching. The
relay matches capability names **exactly**: a stage that asks for `chat.ai`
will only be claimed by a node whose latest heartbeat advertised `chat.ai`.

---

## 7. Refresh and recover credentials

### Refresh the runtime token

Runtime tokens expire after the configured TTL (default 7 days). Before expiry,
refresh the token:

```bash
curl -X POST "http://${RELAY_HOST}:8788/relay/v2/auth/refresh" \
  -H "Authorization: Bearer rt_..." \
  -H "Content-Type: application/json" \
  -d '{"requested_credential": "runtime_token"}'
```

Save the new token immediately. The old token becomes invalid.

### Refresh the registration secret

```bash
curl -X POST "http://${RELAY_HOST}:8788/relay/v2/auth/refresh" \
  -H "Authorization: Bearer rt_..." \
  -H "Content-Type: application/json" \
  -d '{"requested_credential": "registration_secret"}'
```

### Recover a lost runtime token

If the runtime token was lost, use the registration secret:

```bash
curl -X POST "http://${RELAY_HOST}:8788/relay/v2/auth/refresh" \
  -H "Content-Type: application/json" \
  -d '{
    "node_id": "V34ETT74",
    "registration_secret": "rs_...",
    "requested_credential": "runtime_token"
  }'
```

The response contains a new runtime token **and a new registration secret**. The
previous runtime token is invalidated and the old registration secret is rotated.
Save both credentials immediately:

```python
data = r.json()
save_token(data["token"])                          # ai-relay-agent.token
state["registration_secret"] = data["registration_secret"]
STATE_FILE.write_text(json.dumps(state, indent=2)) # ai-relay-agent.json
```

If both credentials expired, the node must be re-registered.

---

## 8. Claim work

With a valid runtime token, a node can claim a stage that matches one of its
capabilities:

```bash
curl -X POST "http://${RELAY_HOST}:8788/relay/v2/scheduler/claim" \
  -H "Authorization: Bearer rt_..." \
  -H "Content-Type: application/json" \
  -d '{"capability": "chat"}'
```

If work is available, the relay returns a stage:

```json
{
  "claimed": true,
  "stage": {
    "stage_id": "stg_...",
    "task_id": "tsk_...",
    "stage_name": "answer",
    "capability": "chat",
    "payload": {
      "question": "What is the current time in Tokyo?"
    }
  }
}
```

If nothing matches:

```json
{
  "claimed": false,
  "stage": null
}
```

The node should poll again after a short delay (1–3 seconds).

| Scenario | HTTP Status | Response Body |
|---|---|---|
| Task available | 200 | `{"claimed": true, "stage": {...}}` |
| No task available | 200 | `{"claimed": false, "stage": null}` |
| Invalid or expired token | 401 | `{"detail": "Invalid token"}` |
| Capability not registered | 403 | `{"detail": "Capability not registered"}` |

---

## 9. Complete or fail a stage

After finishing the work, report the result:

```bash
curl -X POST "http://${RELAY_HOST}:8788/relay/v2/scheduler/stages/stg_.../complete" \
  -H "Authorization: Bearer rt_..." \
  -H "Content-Type: application/json" \
  -d '{
    "node_id": "V34ETT74",
    "task_id": "tsk_...",
    "result": {"answer": "It is 21:45 in Tokyo."}
  }'
```

If the work fails, put the error inside `result`:

```bash
curl -X POST "http://${RELAY_HOST}:8788/relay/v2/scheduler/stages/stg_.../complete" \
  -H "Authorization: Bearer rt_..." \
  -H "Content-Type: application/json" \
  -d '{
    "node_id": "V34ETT74",
    "task_id": "tsk_...",
    "result": {"error": "Model not available"}
  }'
```

---

## 10. Submitting work to the relay

A node is not the only thing that can create work. Dashboard users, other
nodes, and HTTP clients submit tasks to the relay scheduler.

```bash
curl -X POST "http://${RELAY_HOST}:8788/relay/v2/scheduler/tasks" \
  -H "Authorization: Bearer <admin-or-node-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "task_name": "answer-chat-question",
    "stages": [
      {
        "stage_name": "answer",
        "capability": "chat",
        "payload": {"question": "What is the current time in Tokyo?"}
      }
    ],
    "priority": 1
  }'
```

Response:

```json
{
  "task_id": "tsk_abc123",
  "status": "queued"
}
```

The relay matches the `capability` of each stage against online nodes and
routes the stage to a matching node.

### Decision-task pattern (service nodes)

KI-less service nodes may need human or AI judgment to continue. Instead of
guessing, they submit a decision task back to the relay:

```bash
curl -X POST "http://${RELAY_HOST}:8788/relay/v2/scheduler/tasks" \
  -H "Authorization: Bearer rt_..." \
  -H "Content-Type: application/json" \
  -d '{
    "task_name": "storage.decide-target-path",
    "stages": [
      {
        "stage_name": "decide",
        "capability": "llm.decide_cleanup",
        "payload": {"file_name": "image.png", "usage_ratio": 0.92}
      }
    ],
    "priority": 5
  }'
```

A KI-capable node claims the decision stage, decides, and completes it. The
service node can later read the decision result or receive the next execution
stage.

See `nodes-design.md` for the full self-care pattern.

---

## 11. Node types

### KI-capable node

Claim → understand → execute → complete. Execution may use local tools.

```python
def execute_stage(stage):
    payload = stage["payload"]
    capability = stage["capability"]

    if capability == "image.generate":
        return {"image_path": str(generate_image(payload["prompt"]))}
    if capability == "chat":
        return {"answer": local_llm_chat(payload["question"])}
    return {"error": f"Unknown capability: {capability}"}
```

### KI-less service node

Claim → check → execute directly or post a decision task to the relay.

```python
def execute_stage(stage):
    payload = stage["payload"]

    if not payload.get("target_path"):
        submit_decision_task(stage)
        return {"status": "needs_decision"}

    archive_file(payload["file_name"], payload["target_path"])
    return {"status": "completed", "archived_to": payload["target_path"]}
```

---

## 12. Minimal worker reference

```python
#!/usr/bin/env python3
"""Minimal AI Relay worker reference implementation."""

import json
import os
import sys
import time
from pathlib import Path

import httpx

BASE_DIR = Path.home() / ".relay"
STATE_FILE = BASE_DIR / "ai-relay-agent.json"
TOKEN_FILE = BASE_DIR / "ai-relay-agent.token"


def load_state():
    return json.loads(STATE_FILE.read_text())


def load_token():
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip()
    return None


def save_token(token):
    tmp = TOKEN_FILE.with_suffix(".tmp")
    tmp.write_text(token + "\n")
    tmp.rename(TOKEN_FILE)


def api_post(path, token=None, json_body=None, timeout=20):
    state = load_state()
    url = f"{state['base_url'].rstrip('/')}{path}"
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.post(url, headers=headers, json=json_body, timeout=timeout)


def heartbeat(token):
    state = load_state()
    caps = state.get("capabilities", [])
    r = api_post(
        "/relay/v2/discovery/heartbeat",
        token=token,
        json_body={
            "available": True,
            "load": 0.0,
            "queue_depth": 0,
            "capabilities": caps,
        },
    )
    r.raise_for_status()
    return r.json()


def claim(token, capability):
    r = api_post(
        "/relay/v2/scheduler/claim",
        token=token,
        json_body={"capability": capability},
    )
    r.raise_for_status()
    return r.json()


def complete(token, task_id, stage_id, result):
    r = api_post(
        f"/relay/v2/scheduler/stages/{stage_id}/complete",
        token=token,
        json_body={
            "node_id": load_state()["node_id"],
            "task_id": task_id,
            "result": result,
        },
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def refresh_runtime_token(token):
    r = api_post(
        "/relay/v2/auth/refresh",
        token=token,
        json_body={"requested_credential": "runtime_token"},
    )
    r.raise_for_status()
    data = r.json()
    new_token = data.get("token")
    if new_token:
        save_token(new_token)
    return new_token or token


def recover_runtime_token():
    state = load_state()
    r = api_post(
        "/relay/v2/auth/refresh",
        json_body={
            "node_id": state["node_id"],
            "registration_secret": state["registration_secret"],
            "requested_credential": "runtime_token",
        },
    )
    r.raise_for_status()
    data = r.json()
    new_token = data.get("token")
    new_rs = data.get("registration_secret")
    if new_token:
        save_token(new_token)
    if new_rs:
        state["registration_secret"] = new_rs
        STATE_FILE.write_text(json.dumps(state, indent=2))
    return new_token


def handle_auth_error(token):
    try:
        return refresh_runtime_token(token)
    except Exception:
        return recover_runtime_token()


def execute_stage(stage):
    # Replace with real work.
    return {"status": "completed", "output": "done"}


def main_loop():
    token = load_token()
    if not token:
        token = recover_runtime_token()
    if not token:
        print("no token available", file=sys.stderr)
        sys.exit(1)

    state = load_state()
    caps = [c["name"] if isinstance(c, dict) else c for c in state.get("capabilities", [])]

    while True:
        try:
            hb = heartbeat(token)
            print(f"heartbeat {hb.get('status')}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                token = handle_auth_error(token)
                continue
            print(f"heartbeat failed: {exc}", file=sys.stderr)

        for cap in caps:
            try:
                resp = claim(token, cap)
                stage_data = resp.get("stage")
                if stage_data:
                    print(f"claimed {cap} stage {stage_data['stage_id']}")
                    result = execute_stage(stage_data)
                    complete(token, stage_data["task_id"], stage_data["stage_id"], result)
                    print(f"completed {stage_data['stage_id']}")
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (401, 403):
                    token = handle_auth_error(token)
                else:
                    print(f"claim failed: {exc}", file=sys.stderr)
            except Exception as exc:
                print(f"execution failed: {exc}", file=sys.stderr)

        time.sleep(0.5)


if __name__ == "__main__":
    main_loop()
```

For production use the generic `Poller` class from `nodes/storage-node/poller.py`
or the Hermes skill `ai-relay-agent-node` instead of this minimal example.

---

## 13. Monitoring status file

The reference poller writes `~/.relay/worker_status.json` after every
heartbeat. External health checks can read it.

```json
{
  "pid": 18438,
  "node_id": "V34ETT74",
  "started_at": "2026-06-23T00:00:00+00:00",
  "last_heartbeat": "2026-06-23T00:05:00+00:00",
  "heartbeat_status": "ok",
  "capabilities": ["chat", "storage"],
  "tasks_completed": 42,
  "tasks_failed": 3,
  "token_present": true,
  "error": null
}
```

A simple health check:

```bash
#!/bin/bash
STATUS_FILE="$HOME/.relay/worker_status.json"
if [ ! -f "$STATUS_FILE" ]; then
    echo "Worker DOWN – no status file"
    exit 1
fi
LAST_HB=$(jq -r '.last_heartbeat' "$STATUS_FILE")
HB_EPOCH=$(date -d "$LAST_HB" +%s)
NOW=$(date +%s)
DIFF=$((NOW - HB_EPOCH))
if [ "$DIFF" -gt 60 ]; then
    echo "Worker STALE – last heartbeat ${DIFF}s ago"
    exit 1
fi
echo "Worker OK"
```

---

## 14. Helper scripts and examples

| Path | Purpose |
|------|---------|
| `examples/nodes/node_base.py` | Base class that handles registration, heartbeat, claim, and complete loops |
| `examples/nodes/relay_client.py` | HTTP client for the relay API |
| `nodes/common/poller.py` | Generic production poller for any node type |
| `nodes/common/relay_config.json.example` | Example config for the common poller |
| `nodes/storage-node/poller.py` | Storage-specific wrapper around the common poller |
| `nodes/storage-node/storage_node.py` | Example service node using the poller |
| `nodes/storage-node/register.py` | One-time registration for the storage node |
| `scripts/manual_node_test.py` | Manual end-to-end node test |

---

## 15. Checklist for a new node

- [ ] Know the relay URL from configuration or the user
- [ ] Prepare `~/.relay/ai-relay-agent.json` with the planned `node_name`, `capabilities`, and `base_url`
- [ ] Register via `/relay/v2/auth/register`
- [ ] Save `node_id` and `registration_secret` into the state file
- [ ] Wait until the relay administrator activates the node
- [ ] Poll `/relay/v2/auth/status` **unauthenticated** to detect activation
- [ ] Recover or receive the runtime token and save it to `~/.relay/ai-relay-agent.token`
- [ ] Implement the worker code with refresh and recovery logic (or use the reference poller)
- [ ] Start sending heartbeats every 8 seconds
- [ ] Start the claim → execute → complete loop
- [ ] Monitor credential lifetimes via `/relay/v2/auth/status` and refresh before expiry
- [ ] Ensure `~/.relay/worker_status.json` is written for external monitoring
- [ ] Configure a LaunchAgent, systemd unit, or container restart policy

---

## 16. Common mistakes

| Mistake | Consequence | Fix |
|---------|-------------|-----|
| Forgetting heartbeats | Node marked offline | Send heartbeats every 8 seconds |
| Losing the registration secret | Cannot refresh tokens | Keep `ai-relay-agent.json` safe |
| Claiming with the wrong capability | No tasks received | Use one of the registered capabilities |
| Node stays pending forever | Nobody activated it | Ask the relay administrator to activate it |
| Runtime token expired | All authenticated requests fail | Refresh via `/relay/v2/auth/refresh`. If lost, recover with `registration_secret`. |
| Re-registering with the same `node_id` | 409 Conflict from `/relay/v2/auth/register` | Recover the runtime token with the registration secret; only register once. |
| Wrong heartbeat body fields | 422 Unprocessable Content | Use `available`, `load`, `queue_depth`, `capabilities`. `node_id` comes from the token. |
| Calling `/auth/status` to rotate tokens | Nothing happens or 401 | Use `/relay/v2/auth/refresh` for rotation. |
| Service node makes AI decisions | Wrong decisions, no audit trail | Post a decision task back to the relay. |

---

## 17. Relay administrator tasks

The following actions are **not** performed by a node. They are done by the
human or KI agent that operates the relay:

- Install and start the relay server
- Create the master admin seed
- Bootstrap the first human admin in the dashboard
- Activate pending nodes in the dashboard
- Issue new runtime tokens when needed
- Delete nodes from the cluster

For these tasks, the administrator should read `setup.md` and `dashboard.md`.

> Master-seed login is intentionally unavailable during normal operation. If
> every human admin is locked out, the administrator must enable recovery
> mode first (`RELAY_ENABLE_MASTER_SEED_LOGIN=true`).

---

## 18. Next steps

- For understanding tokens, see `token-concept.md`.
- For node design patterns, see `nodes-design.md`.
- For installing and configuring the relay, see `setup.md`.
- For managing users and approving nodes, see `dashboard.md`.
- For the message board design, see `design-board.md`.
