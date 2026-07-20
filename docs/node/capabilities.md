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

## Capability types

Every capability has a **type** that describes *how* work is executed:

| Type | Suffix | Execution | Example |
|------|--------|-----------|---------|
| **KI-capable** | `.ai` | Delegated to a local AI (Hermes, LLM). The AI interprets the payload, chooses tools, and returns a result. | `chat.ai`, `agent.ai`, `code.ai` |
| **KI-less / tool** | `.native` | Direct execution — a script, binary, or hard-coded handler. No AI involved. | `storage.archive.native`, `image.generate.mflux` |

A single node can offer **both** types side by side. For example, a worker
might advertise `chat.ai` (KI-capable, handled by Hermes) and
`image.generate.mflux` (tool, runs FLUX directly) in the same heartbeat.
The handler for each capability decides how work is executed — the node-cli
daemon is agnostic to the type.

## chat.ai vs agent.ai

Both are KI-capable (`.ai` suffix), but they serve different purposes:

| | `chat.ai` | `agent.ai` |
|---|---|---|
| **Backend** | `hermes -z` (subprocess) | Hermes API Server (HTTP) |
| **Session** | None — new session every call | Persistent session across calls |
| **Context** | Only the current prompt | Can maintain multi-turn context |
| **Tools** | Limited to what `-z` provides | Full Hermes toolset |
| **Use case** | Simple, stateless queries ("What time is it?") | Complex multi-step workflows ("Update the worker and restart") |
| **Latency** | Higher (process startup each time) | Lower (server stays running) |

**When to use which:**

- `chat.ai` — quick questions, simple prompts, no tool access needed.
  The handler runs `hermes -z "<prompt>"` and returns the response.

- `agent.ai` — complex tasks that require planning, tool use, or
  multi-step execution ("git pull, check capabilities, restart daemon").
  The handler sends the payload to a local Hermes API Server
  (`http://localhost:8080/v1/chat/completions`) which keeps a persistent
  session and has access to all tools.

**Example `agent.ai` capability profile:**

```yaml
- name: agent.ai
  type: ai
  description: "Full Hermes agent with persistent session and all tools."
  auto_publish: true
  claimable: true
  handler: /opt/relay/handlers/agent-handler.sh
  max_parallel: 1
  timeout: 600
  input_schema:
    fields:
      task:
        name: task
        type: string
        required: true
        description: "The task description for the agent to execute."
```

The `agent-handler.sh` would POST to the local Hermes API Server
instead of running `hermes -z`:

## node-cli capability profiles

The generic `node-cli` daemon is **capability-agnostic**: all capabilities are
defined in external YAML profiles. The daemon reads only
`~/.relay/capabilities.active.yaml`; working profiles live in
`~/.relay/capabilities.d/`.

```yaml
capabilities:
  - name: chat.ai
    version: "1.0.0"
    type: ai                              # optional: ai | tool | script | workflow | resource
    description: "General conversational AI — accepts a prompt, question, or message and returns a text response."
    auto_publish: true                    # include in every heartbeat
    claimable: true                       # daemon may claim stages for this capability
    handler: /opt/relay/handlers/chat-ai.sh   # required when claimable: true
    max_parallel: 2                       # in-flight handler limit (default: 1)
    timeout: 300                          # handler timeout in seconds (default: 300)
    input_schema:                         # optional, documents expected payload fields
      fields:
        prompt:
          name: prompt
          type: string
          required: false
          description: "The main instruction or request for the AI."
        message:
          name: message
          type: string
          required: false
          description: "Alternative to prompt — a short message or greeting."
    dashboard_page: false                 # optional, default false — see "Dashboard pages" below
```

### Capability dashboard pages (T-048)

A capability can provide its own HTML dashboard page that operators and
admins see in the relay dashboard's **Capabilities** tab. The page is
embedded in an `<iframe>` and served from
`GET /relay/v2/capabilities/<name>/dashboard-page`.

To enable it:

1. Set `dashboard_page: true` in the capability's YAML profile.
2. Publish the profile (`node-cli capabilities publish <profile>`).
3. Build the HTML page locally and upload it:

   ```bash
   node-cli artifact upload ./dashboard.html --capability <capability-name>
   ```

The server stores the file at
`~/.relay/capability-pages/<name>/dashboard.html` — **separate from the
artifact store**, no artifact DB entry is created. Re-uploading
overwrites the previous page. The path is deterministically derived
from the capability name, so there is no `dashboard_artifact_id` to
track.

The dashboard lists all capabilities whose `dashboard_page: true` and
that have at least one available node. Clicking a card loads the
capability page in a same-origin iframe.

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
`handler`, `max_parallel`/`timeout` not positive integers,
`auto_publish`/`claimable`/`dashboard_page` not boolean, or `version` not
a non-empty string. The optional `description` field is preserved through
the pipeline and forwarded to the relay in heartbeats.
On error the active profile is never touched.

### Capability metadata forwarded to the server (T-053)

The daemon's heartbeat includes the following fields for each advertised
capability, when they are present in the YAML profile:

| Field | Purpose |
|---|---|
| `name`, `version` | Capability identity (always sent) |
| `available` | Computed from `max_parallel` vs. in-flight stages |
| `dashboard_page` | Whether a dashboard page was uploaded |
| `type` | Capability type (`ai`, `tool`, `script`, `workflow`, `resource`) |
| `description` | Human-readable description |
| `input_schema` | Expected payload fields (documented below) |

The server stores `description`, `type` and `input_schema` in the
normalized `node_capabilities` index. When a node claims a stage or
queries a task, the scheduler resolves `capability_details` inline so
the claiming handler sees the expected payload shape without an extra
discovery round-trip:

```json
"capability_details": {
  "name": "chat.ai",
  "type": "ai",
  "description": "General conversational AI — accepts a prompt, ...",
  "input_schema": { "fields": { "prompt": { "type": "string", "required": false } } }
}
```

For the full `node-cli` command reference see [node-cli-reference.md](node-cli-reference.md).
