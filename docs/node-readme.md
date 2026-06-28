# AI Relay — Node Connection Guide

Written from the perspective of a node that wants to join an AI Relay cluster.
It covers the minimum needed to connect, register, activate, heartbeat, and
claim work. Deep dives live in the linked companion documents.

## 1. What you need

One piece of information: the relay URL.

- `http://192.168.1.50:8788`
- `http://ai-relay.local:8788` (if your network supports mDNS)

If you do not know the URL, ask the person who installed the relay.

## 2. Register once

```bash
curl -X POST "http://${RELAY_HOST}:8788/relay/v2/auth/register" \
  -H "Content-Type: application/json" \
  -d '{
    "node_name": "my-node",
    "endpoint": "http://192.168.1.60:9000",
    "role": "service",
    "capabilities": [{"name": "chat", "version": "1.0.0"}]
  }'
```

Save the response — it contains your `node_id`, a temporary token (`tp_…`,
24 h), and a `registration_secret` (`rs_…`, 12 h):

```json
{
  "node_id": "V34ETT74",
  "status": "pending",
  "token": "tp_...",
  "registration_secret": "rs_..."
}
```

## 3. Node state file

Persist the response in `~/.relay/ai-relay-agent.json`:

```json
{
  "node_id": "V34ETT74",
  "node_name": "my-node",
  "endpoint": "http://192.168.1.60:9000",
  "registration_secret": "rs_...",
  "capabilities": [{"name": "chat", "version": "1.0.0"}],
  "base_url": "http://192.168.1.50:8788"
}
```

The runtime token is stored separately in `~/.relay/ai-relay-agent.token` so it
can be rotated without rewriting the state file.

> See **[token-lifecycle.md](node-operator/token-lifecycle.md)** for the full
> credential lifecycle, refresh, and recovery flows.

## 4. Wait for activation

A newly registered node is `pending` and cannot claim work. Poll
`/relay/v2/auth/status` **without** a Bearer token until the relay admin
activates the node:

```bash
curl -X POST "http://${RELAY_HOST}:8788/relay/v2/auth/status" \
  -H "Content-Type: application/json" \
  -d '{"node_id": "V34ETT74", "registration_secret": "rs_..."}'
```

```json
{ "node_id": "V34ETT74", "status": "pending", "message": "Awaiting admin activation" }
```

After approval the admin receives a runtime token and may provide it to the
node, or the node recovers it with the registration secret. The relay admin
activates nodes in the dashboard or via the admin API — a node cannot approve
itself.

## 5. Heartbeat basics

Send a heartbeat every **8 seconds**. The first valid heartbeat moves the
node from `approved` to `online`:

```bash
curl -X POST "http://${RELAY_HOST}:8788/relay/v2/discovery/heartbeat" \
  -H "Authorization: Bearer rt_..." \
  -H "Content-Type: application/json" \
  -d '{
    "available": true,
    "load": 0.0,
    "queue_depth": 0,
    "capabilities": [{"name": "chat", "version": "1.0.0"}]
  }'
```

A node that misses too many heartbeats is marked `offline` and stops receiving
tasks. Send a valid heartbeat to come back `online`. `endpoint` is set during
registration; resend it only if it changed at runtime.

> Capabilities, suffixes (`.native`/`.ai`/`.relay`), and the `node-cli`
> profile format are documented in **[capabilities.md](node-operator/capabilities.md)**.

## 6. Claim work

```bash
curl -X POST "http://${RELAY_HOST}:8788/relay/v2/scheduler/claim" \
  -H "Authorization: Bearer rt_..." \
  -H "Content-Type: application/json" \
  -d '{"capability": "chat"}'
```

```json
{
  "claimed": true,
  "stage": {
    "stage_id": "stg_...",
    "task_id": "tsk_...",
    "stage_name": "answer",
    "capability": "chat",
    "payload": {"question": "What is the current time in Tokyo?"}
  }
}
```

If nothing matches: `{"claimed": false, "stage": null}` — poll again after
1–3 seconds. Capability names are matched **exactly**.

| Scenario | HTTP | Body |
|---|---|---|
| Task available | 200 | `{"claimed": true, "stage": {...}}` |
| No task | 200 | `{"claimed": false, "stage": null}` |
| Invalid/expired token | 401 | `{"detail": "Invalid token"}` |
| Capability not registered | 403 | `{"detail": "Capability not registered"}` |

## 7. Complete or fail a stage

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

On failure, put the error inside `result`: `{"error": "Model not available"}`.

## 8. Artifacts (file hand-off)

Upload a file (default limit **100 MiB**) and pass the `artifact_id` in stage
results/payloads instead of base64-encoding data:

```bash
curl -X POST "http://${RELAY_HOST}:8788/relay/v2/storage/upload" \
  -H "Authorization: Bearer rt_..." \
  -H "Content-Type: multipart/form-data" \
  -F "file=@/path/to/image.png" \
  -F "task_id=tsk_abc123" -F "stage_id=stg_answer"
```

```json
{ "artifact_id": "artifact_a1B2c3D4", "name": "image.png", "size_bytes": 123456 }
```

Download with `GET /relay/v2/storage/files/{artifact_id}`, metadata with
`/meta`, list with `GET /relay/v2/storage/list?task_id=…`, delete with
`DELETE /relay/v2/storage/files/{artifact_id}`.

## 9. Minimal worker reference

```python
#!/usr/bin/env python3
"""Minimal AI Relay worker — heartbeat + claim + complete loop."""
import json, sys, time
from pathlib import Path
import httpx

BASE = Path.home() / ".relay"
STATE_FILE = BASE / "ai-relay-agent.json"
TOKEN_FILE = BASE / "ai-relay-agent.token"

def state(): return json.loads(STATE_FILE.read_text())
def token(): return TOKEN_FILE.read_text().strip() if TOKEN_FILE.exists() else None
def save_token(t): TOKEN_FILE.write_text(t + "\n")

def post(path, tok=None, body=None):
    s = state()
    r = httpx.post(f"{s['base_url'].rstrip('/')}{path}",
                   headers={"Authorization": f"Bearer {tok}"} if tok else {},
                   json=body, timeout=20)
    r.raise_for_status(); return r.json()

def refresh(tok):
    try:
        d = post("/relay/v2/auth/refresh", tok, {"requested_credential": "runtime_token"})
        save_token(d["token"]); return d["token"]
    except Exception:
        s = state()
        d = post("/relay/v2/auth/refresh", body={
            "node_id": s["node_id"], "registration_secret": s["registration_secret"],
            "requested_credential": "runtime_token"})
        save_token(d["token"])
        s["registration_secret"] = d["registration_secret"]
        STATE_FILE.write_text(json.dumps(s, indent=2))
        return d["token"]

def main():
    tok = token() or refresh(None)
    caps = [c["name"] if isinstance(c, dict) else c for c in state().get("capabilities", [])]
    while True:
        try:
            post("/relay/v2/discovery/heartbeat", tok, {
                "available": True, "load": 0.0, "queue_depth": 0, "capabilities": caps})
            for cap in caps:
                resp = post("/relay/v2/scheduler/claim", tok, {"capability": cap})
                st = resp.get("stage")
                if st:
                    result = {"status": "completed"}   # replace with real work
                    post(f"/relay/v2/scheduler/stages/{st['stage_id']}/complete", tok,
                         {"node_id": state()["node_id"], "task_id": st["task_id"], "result": result})
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (401, 403): tok = refresh(tok)
            else: print(f"err: {e}", file=sys.stderr)
        time.sleep(0.5)

if __name__ == "__main__": main()
```

For production use the generic `Poller` in `nodes/common/poller.py` or the
Hermes skill `ai-relay-agent-node`. The poller writes
`~/.relay/worker_status.json` after every heartbeat for external monitoring.

## 10. Checklist for a new node

- [ ] Know the relay URL
- [ ] Prepare `~/.relay/ai-relay-agent.json` with `node_name`, `capabilities`, `base_url`
- [ ] Register via `/relay/v2/auth/register`
- [ ] Save `node_id` and `registration_secret`
- [ ] Wait until the admin activates the node (poll `/auth/status`)
- [ ] Obtain the runtime token (provided or recovered) → `ai-relay-agent.token`
- [ ] Start heartbeats every 8 seconds
- [ ] Run the claim → execute → complete loop
- [ ] Refresh tokens before expiry; recover with the registration secret if lost
- [ ] Configure a systemd unit, LaunchAgent, or container restart policy

## Next steps

- **[token-lifecycle.md](node-operator/token-lifecycle.md)** — token types, refresh, recovery
- **[capabilities.md](node-operator/capabilities.md)** — capability formats, suffixes, `node-cli` profiles
- **[../nodes-design.md](../nodes-design.md)** — node architecture & decision-task pattern
- **[../setup.md](../setup.md)** — relay installation & configuration
- **[../dashboard.md](../dashboard.md)** — node approval & dashboard usage
