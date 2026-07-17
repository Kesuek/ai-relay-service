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

Capability names are lowercase, dot-separated namespaces. The suffix
describes *how* the node executes the stage and is **required** for every
concrete capability a node advertises — a bare core name such as `chat` or
`storage.archive` is a category, not an executable offer.

| Suffix | Meaning | Required for | Example |
|---|---|---|---|
| `.native` | Runs directly on the node, no local AI. | **Every KI-less / service node.** | `storage.archive.native`, `db.board.create.native` |
| `.ai` | KI-capable; the node delegates to its local AI. | KI-capable worker nodes. | `chat.ai`, `code.ai`, `board.reply.generate.ai` |
| `.relay` | Relay-internal orchestration capability. | Relay-internal stages only. | `llm.decide_cleanup.relay` |

> **Rule of thumb:** if a node has no local AI, **all** of its capabilities
> carry the `.native` suffix — including database/service nodes like the
> db-node (`db.board.create.native`, `db.post.read.native`, …). The relay
> matches capability names **exactly**, so advertising `db.board.create`
> when a stage requests `db.board.create.native` will not match.

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

See [../concepts.md](../concepts.md) for the full self-care pattern.

## node-cli capability profiles

The generic `node-cli` daemon is **capability-agnostic**: all capabilities are
defined in external YAML profiles. The daemon reads only
`~/.relay/capabilities.active.yaml`; working profiles live in
`~/.relay/capabilities.d/`.

```yaml
capabilities:
  - name: chat.ai
    version: "1.0.0"
    description: "General conversational AI agent"  # optional, human-readable
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
**stdout** must be valid JSON (the result dict). The daemon captures
**stderr** and writes it to the daemon log for debugging — it is never sent
to the relay as the result.

| Outcome | What the daemon does | Result stored on the stage |
|---|---|---|
| Exit `0`, stdout is valid JSON | Complete the stage | The parsed stdout dict |
| Exit `0`, stdout is **not** valid JSON | Fail the stage | `{"error": "handler produced invalid JSON on stdout"}` |
| Exit non-zero (any code `N`) | Fail the stage | `{"error": "<stderr trimmed>"}` if stderr is non-empty, else `{"error": "handler exited with code N"}` |
| Timeout exceeded | `SIGTERM` then `SIGKILL` after a short grace | `{"error": "handler timeout after Ns"}` |
| `SIGKILL` / host shutdown while claimed | The stage stays `claimed` until `claim_ttl_seconds` (default 60 s) elapses, then the scheduler releases it back to `pending` for another node to claim | — |

Key points:

- **stdout is the contract.** Only stdout is interpreted as the result.
  Write logs/diagnostics to stderr.
- **Exit codes are meaningful.** `0` = success, anything else = failure.
- **Timeouts don't hang the daemon.** The handler is killed and the stage
  is failed with a clear error message; the scheduler re-queues it (up to
  `max_retries`).
- **Crash safety.** If the daemon itself is killed mid-claim, the stage is
  not lost — the relay's claim-TTL watchdog releases it automatically. No
  manual intervention needed.

### Validation rules

A profile is invalid if: YAML syntax error, `capabilities` missing/not a list,
any capability missing `name`, duplicate names, `claimable: true` without
`handler`, `max_parallel`/`timeout` not positive integers, or
`auto_publish`/`claimable` not boolean. The optional `description` field is
preserved through the pipeline and forwarded to the relay in heartbeats.
On error the active profile is never touched.

For the full `node-cli` command reference see [node-cli-reference.md](node-cli-reference.md).
