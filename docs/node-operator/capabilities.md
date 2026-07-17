# Capabilities

Capabilities are the routing keys the relay uses to match stages to nodes.
A node advertises its capabilities in every heartbeat; the scheduler matches
capability names **exactly**.

## Defining capabilities

Capabilities may be sent as objects or plain strings:

```json
{ "capabilities": ["chat.ai", "code.ai"] }
```

```json
{ "capabilities": [{"name": "chat.ai", "version": "1.0.0"}] }
```

A node can change what it offers at runtime by sending different capabilities
in subsequent heartbeats. The scheduler always uses the most recent heartbeat.

## Naming & suffixes

| Suffix | Meaning | Example |
|---|---|---|
| `.native` | Runs on the relay host (storage, archive) | `storage.archive.native` |
| `.ai` | KI-capable, the node delegates to its local AI | `chat.ai`, `code.ai` |
| `.relay` | Relay-internal orchestration capability | `llm.decide_cleanup.relay` |

Capability names are matched **exactly**: a stage requesting `chat.ai` is only
claimed by a node whose latest heartbeat advertised `chat.ai`.

## Heartbeat with capabilities

```bash
curl -X POST "http://${RELAY_HOST}:8788/relay/v2/discovery/heartbeat" \
  -H "Authorization: Bearer rt_..." \
  -H "Content-Type: application/json" \
  -d '{
    "available": true,
    "load": 0.0,
    "queue_depth": 0,
    "capabilities": [{"name": "chat.ai", "version": "1.0.0"}]
  }'
```

`endpoint` is set during registration; send it again only if it changed at
runtime.

## Node types

**KI-capable node** — claim → understand → execute → complete. Hand the stage
payload to the local AI rather than hard-coding tool calls; the AI chooses
tools and how to combine them.

**KI-less service node** — claim → check → execute directly, or post a
decision task back to the relay when AI judgment is needed:

```python
def execute_stage(stage):
    payload = stage["payload"]
    if not payload.get("target_path"):
        submit_decision_task(stage)          # KI node claims it later
        return {"status": "needs_decision"}
    archive_file(payload["file_name"], payload["target_path"])
    return {"status": "completed"}
```

See `nodes-design.md` for the full self-care pattern.

## node-cli capability profiles

The generic `node-cli` daemon is **capability-agnostic**: all capabilities are
defined in external YAML profiles. The daemon reads only
`~/.relay/capabilities.active.yaml`; working profiles live in
`~/.relay/capabilities.d/`.

```yaml
capabilities:
  - name: chat.ai
    version: "1.0.0"
    auto_publish: true          # include in every heartbeat
    claimable: true             # daemon may claim stages for this capability
    handler: /opt/relay/handlers/chat-ai.sh   # required when claimable: true
    max_parallel: 2            # in-flight handler limit (default: 1)
    timeout: 300                # handler timeout in seconds (default: 300)
```

Publish flow:

```
Operator edits capabilities.d/default.yaml
        ↓
node-cli capabilities validate default    ← validates without touching active
        ↓
node-cli capabilities publish default      ← atomic write to active.yaml + SIGHUP
        ↓
Daemon picks up change at next heartbeat (mtime check) or via SIGHUP
```

### Handler contract

A handler is an external subprocess. Environment variables `RELAY_STAGE_ID`,
`RELAY_TASK_ID`, `RELAY_CAPABILITY`, `RELAY_NODE_ID`, `RELAY_BASE_URL`,
`RELAY_TOKEN_FILE` are set. **Stdin** receives the stage payload as JSON;
**stdout** must be valid JSON (the result dict). Exit 0 → complete, non-zero
→ `{"error": ...}`, timeout → `{"error": "handler timeout after Ns"}`.

### Validation rules

A profile is invalid if: YAML syntax error, `capabilities` missing/not a list,
any capability missing `name`, duplicate names, `claimable: true` without
`handler`, `max_parallel`/`timeout` not positive integers, or
`auto_publish`/`claimable` not boolean. On error the active profile is never
touched.

For the full `node-cli` command reference see [node-cli-reference.md](node-cli-reference.md).
