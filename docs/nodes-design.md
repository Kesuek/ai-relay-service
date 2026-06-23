# AI Relay — Node Design Philosophy

This document describes how nodes in the AI Relay ecosystem should be designed.
It covers two broad categories:

1. **KI-capable nodes** — classical AI agents that reason, decide, and converse.
2. **KI-less service nodes** — specialised "dumb" workers that execute raw
   actions and ask the relay for decisions when one is needed.

## Core principle

**The relay is the brain. Nodes are hands.**

A node should not decide what to do next on its own. It advertises what it
*can* do (capabilities), waits for the relay to send matching work, executes the
stage, and reports the result. If a decision is required, the node posts a
decision task back to the relay and lets a KI-capable node handle it.

## 1. KI-capable nodes

These are traditional AI agents. They can:

- Understand natural language instructions
- Plan multi-step workflows
- Generate content (text, code, images, audio)
- Make judgement calls
- Interact with users

### Examples

| Capability | Example node | Responsibility |
|------------|--------------|----------------|
| `chat` | Hermes / assistant node | Conversational interface, general questions |
| `code` | Coding agent node | Write, review, and debug code |
| `web` | Research agent node | Search the web, summarise pages |
| `vision` | Vision agent node | Analyse images, describe contents |
| `llm.decide_cleanup` | Storage decision node | Decide which files to delete when quota is hit |
| `llm.plan_task` | Orchestrator node | Break a user request into relay task DAGs |

### Design rules

- Register one or more capability names that match the kind of work you do.
- Poll `POST /relay/v2/scheduler/claim` with your capability.
- Read the stage payload carefully; it contains the user's original intent and
  any context produced by earlier stages.
- Return structured results so downstream stages can continue the workflow.
- Never perform destructive actions unless the stage explicitly requests them.
- When in doubt, return a request for clarification instead of guessing.

## 2. Node execution modes

A capability can be provided in different ways. The same logical service, for
example image generation, may be implemented differently on different nodes.
Document the mode with a label suffix so the relay and users know what they are
talking to.

| Mode | Suffix | Meaning | Example |
|------|--------|---------|---------|
| **Native** | `.native` | The node executes the tool directly. No local AI is invoked. | `image.generate.native` |
| **AI** | `.ai` | The node asks its local AI to decide and execute. | `image.generate.ai` |
| **Relay** | `.relay` | The node forwards the request to another specialised node. | `image.generate.relay` |

A worker node demonstrated the `.native` pattern for image generation: the node
claimed `image.generate` stages and ran the local image-generation tool directly.
The local AI instance was not consulted for every request. This is correct when
the request payload already contains all required parameters.

A node may register both variants:

```json
{
  "capabilities": [
    {"name": "image.generate.native", "version": "1.0.0"},
    {"name": "chat.ai", "version": "1.0.0"}
  ]
}
```

A node should ask the user how a service should be exposed when the choice is
not obvious. For example, during setup the installer can ask:

- "Should image generation run natively on this node, or should the local AI
  decide each invocation?"
- "Should terminal commands be executed directly, or confirmed by the local AI?"

The answer determines the registered capability name.

## 3. KI-less service nodes

These nodes are intentionally "dumb". They have no reasoning capability. They:

- Register narrow, well-defined capabilities (`storage.archive`, `backup`,
  `printer.print`, `switch.toggle`, etc.)
- Execute only the exact operation described in the stage payload
- Report success or failure with raw data
- **Post decision tasks back to the relay** when a judgement call is needed

This is the **self-care pattern**.

### Why KI-less nodes?

| Benefit | Explanation |
|---------|-------------|
| Safety | A dumb node cannot improvise. It only does what the stage says. |
| Simplicity | Small code base, easy to audit, easy to replace. |
| Reliability | Fewer moving parts, deterministic behaviour. |
| Network placement | Can run on constrained devices (NAS, IoT, Docker). |
| Cost | No GPU or large model required. |

### The self-care pattern

A service node detects a problem it is not allowed to decide itself. Instead of
making a choice, it creates a task for a KI-capable node.

Example: the storage node notices disk usage above the threshold.

1. Storage node measures disk usage.
2. Usage is `0.91`, threshold is `0.85`.
3. Storage node posts a task with a `llm.decide_cleanup` stage.
   Payload: current file list, usage ratio, threshold.
4. A KI node claims the stage, analyses the files, and returns a list of
   candidates to delete.
5. Relay creates a follow-up `storage.delete` stage.
6. Storage node claims and executes the deletion.

No KI logic lives inside the storage node.

### Examples of service nodes

| Capability | Node | Responsibility |
|------------|------|----------------|
| `storage.archive` | NAS storage node | Download artifact from relay, write to NAS |
| `storage.list` | NAS storage node | List archived files |
| `storage.delete` | NAS storage node | Delete archived files |
| `storage.quota` | NAS storage node | Report disk usage |
| `backup.snapshot` | NAS backup node | Trigger filesystem snapshots |
| `printer.print` | Printer node | Print documents |
| `switch.toggle` | IoT relay node | Toggle smart home switches |
| `fs.read`, `fs.write` | File-system node | Read or write local files |
| `camera.capture` | Camera node | Take a photo |
| `notify.pushover` | Notification node | Send push notifications |

## 4. Anatomy of a node

Every node, regardless of type, follows the same lifecycle:

```
register → poll approval → heartbeat → claim → execute → complete
```

### Registration

A node registers with the relay and receives:

- `node_id` — unique cluster ID
- `registration_secret` — used to refresh tokens
- `token` — temporary token until approval

```http
POST /relay/v2/auth/register
{
  "node_name": "nas-storage-01",
  "capabilities": [
    {"name": "storage.archive", "version": "1.0.0"},
    {"name": "storage.list", "version": "1.0.0"},
    {"name": "storage.delete", "version": "1.0.0"}
  ]
}
```

### Approval

An admin must approve the node before it can claim work. Use the dashboard or
admin API.

### Heartbeat

The node proves it is alive every few seconds:

```http
POST /relay/v2/discovery/heartbeat
Authorization: Bearer <token>
{
  "node_id": "V34ETT74",
  "status": "online",
  "load": 0.0,
  "queue_depth": 0
}
```

Recommended interval: **8 seconds**.

### Claim

The node asks for work matching one of its capabilities:

```http
POST /relay/v2/scheduler/claim
Authorization: Bearer <token>
{
  "capability": "storage.archive"
}
```

### Execute

The node performs the action described in the returned stage payload.

### Complete

The node reports the result:

```http
POST /relay/v2/scheduler/stages/{stage_id}/complete
Authorization: Bearer <token>
{
  "node_id": "V34ETT74",
  "task_id": "tsk_...",
  "result": {"status": "ok", "path": "/storage/image.png"}
}
```

## 5. Decision boundaries

| Situation | KI node | Service node |
|-----------|---------|--------------|
| User asks "What should I delete?" | Decide | Measure, then ask |
| Disk full | Analyse and recommend | Report usage, then act on command |
| Image generation | Compose prompt, call worker | Run the model |
| File upload | Trigger upload task | Execute upload |
| Print document | Decide when/where to print | Print the document |
| Trigger backup | Decide if backup needed | Run backup command |

The rule of thumb:

> If the answer to "what should happen next?" requires interpretation,
> preference, or judgement, it belongs to a KI node.
>
> If the answer is deterministic and reversible or explicitly authorised,
> it can belong to a service node.

## 6. Self-care in practice

### Storage quota example

```yaml
task_name: storage.cleanup_request.20260621
stages:
  - stage_name: decide
    capability: llm.decide_cleanup
    payload:
      storage_path: /storage
      usage_ratio: 0.91
      threshold: 0.85
      candidates:
        - path: 2026/01/image_001.png
          size: 1048576
          age_days: 180
        - path: 2026/06/image_002.png
          size: 2097152
          age_days: 7
```

A KI node claims `llm.decide_cleanup`, analyses the candidates, and returns:

```json
{
  "delete": [
    "2026/01/image_001.png"
  ],
  "keep": [
    "2026/06/image_002.png"
  ]
}
```

The relay then schedules a `storage.delete` stage with those paths.

### Backup scheduling example

A service node could post:

```yaml
task_name: backup.decide
stages:
  - stage_name: decide
    capability: llm.decide_backup
    payload:
      last_backup: 2026-06-10T03:00:00Z
      disk_usage: 0.91
      important_files_changed: true
```

A KI node returns `{"run_backup": true}`, and the relay schedules
`backup.snapshot`.

## 7. Naming conventions

### Capabilities

Use lowercase, dot-separated namespaces:

- `storage.archive`
- `storage.list`
- `storage.delete`
- `image.generate`
- `printer.print`
- `backup.snapshot`

### Task names

Use descriptive, unique names. Include a timestamp or ID if needed:

- `archive_user_image_20260621_143000`
- `storage.cleanup_request.20260621`

### Node names

Include the host or role:

- `nas-storage-01`
- `m4-macmini-01`
- `hermes-cli-agent`

## 8. Error handling

A node should report failures honestly:

```json
{
  "status": "error",
  "error": "Permission denied writing to /storage/2026/06",
  "retryable": false
}
```

- `retryable: true` — the relay may retry the stage later
- `retryable: false` — a KI node or human should look at it

Never silently swallow errors.

## 9. Security

- Service nodes run with minimal privileges.
- A service node only touches the paths and devices it owns.
- Tokens are stored in `~/.relay/` and never committed.
- KI nodes validate destructive payloads before approving them.
- Unknown capabilities are ignored; nodes cannot claim work outside their role.

## 10. Future directions

Possible additional service nodes that fit this design:

- `camera.capture` — dumb snapshot node
- `audio.play` — play audio files on a speaker
- `mqtt.publish` — publish messages to an MQTT broker
- `zigbee.send` — send Zigbee commands
- `api.forward` — forward HTTP requests to internal services
- `obsidian.append` — append notes to an Obsidian vault
- `hass.call_service` — call Home Assistant services

Each of these would follow the same rule: **execute only, decide never**.

## 11. Summary

- The relay routes tasks based on capabilities.
- A capability can be offered in native, AI, or relay mode.
- KI nodes reason, plan, and decide.
- Service nodes execute raw actions and report facts.
- When a service node needs a decision, it posts a task back to the relay.
- Every node is small, safe, and replaceable.

This design keeps the system modular, auditable, and easy to extend.
