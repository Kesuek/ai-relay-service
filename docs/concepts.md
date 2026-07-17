# AI Relay — Concepts

This document is the central concept reference for the AI Relay Service. It
explains what the relay is, the architecture it follows, how capabilities and
tokens work, the two node types, and the self-care pattern that ties them
together. All other documents link back here for the underlying mental model.

## What is the AI Relay?

The AI Relay is a **KI-less coordination layer** for a cluster of distributed AI
agents and service nodes. It does one thing well: it connects, authenticates,
distributes tasks, and monitors availability. It never runs AI inference or
domain logic itself.

- It owns the registry, heartbeat state, the task DAG, and the event stream.
- It routes work by **capability string** — it does not choose tools, models,
  or parameters.
- Every domain service (Board, Vault, Storage, …) and every AI worker runs as
  an **external node** that registers with the relay over the public v2 API
  and advertises its own capabilities.

Because the core has no domain knowledge, it stays small, auditable, and
replaceable. All intelligence and all domain data live in the nodes.

```
                          ┌────────────────────────┐
                          │   AI Relay Service     │
                          │   core — port 8788     │
                          │  Auth / Discovery /    │
                          │  Scheduler / Events    │
                          └────────────────────────┘
                                    ▲  ▲
           ┌────────────────────────┘  └────────────────────────────┐
           │ heartbeat / claim / complete           register        │
           ▼                                                          ▼
  ┌────────────────────┐                                     ┌────────────────────┐
  │  Service Node      │◄─── KI-less: executes work ───────►│  Worker Node       │
  │  (storage, board)  │         directly over API          │  with local AI     │
  └────────────────────┘                                     └────────────────────┘
```

## Capability concept

Capabilities are the **routing keys** the relay uses to match stages to nodes.

- A node advertises its capabilities in every heartbeat.
- The scheduler matches capability names **exactly**. There is no wildcard
  or implicit fallback.
- A node can change what it offers at runtime by sending different
  capabilities in subsequent heartbeats. The scheduler always uses the most
  recent heartbeat.

### Naming and execution-mode suffixes

Capability names are lowercase, dot-separated namespaces. The suffix
describes *how* the node executes the stage. **Every concrete capability a
node advertises must carry one of these suffixes** — a bare core name such
as `chat` or `storage.archive` is a category, not an executable offer, and
will not match a stage.

| Suffix | Meaning | Example |
|---|---|---|
| `.native` | Runs on the relay host / node directly. No local AI. | `storage.archive.native`, `db.board.create.native` |
| `.ai` | KI-capable; the node delegates to its local AI. | `chat.ai`, `code.ai` |
| `.relay` | Relay-internal orchestration capability. | `llm.decide_cleanup.relay` |

> **All KI-less / service nodes use `.native`.** A database service node
> advertises `db.board.create.native`, `db.post.read.native`, etc. — never
> the bare `db.board.create`. The relay matches names **exactly**, so a
> stage requesting `db.board.create.native` will not be claimed by a node
> that only advertised `db.board.create`.

### Core capability names

To keep clusters interoperable, the ecosystem recommends a small set of core
names. Use these names when they fit; you may register domain-specific names
(e.g. `printer.a4.native`) if the core names do not cover your use case.

| Core name | Typical mode | Meaning |
|---|---|---|
| `chat` | `.ai` | Conversational agent. Answers questions, reasons, interacts with users. |
| `code` | `.ai` | Coding agent. Writes, reviews, debugs code. |
| `web` | `.ai` | Research agent. Searches the web, summarises pages. |
| `vision` | `.ai` | Vision agent. Analyses images, describes contents. |
| `terminal` | `.native` or `.ai` | Executes shell commands, directly or after local AI confirmation. |
| `file` | `.native` | Filesystem operations: read, write, move, delete. |
| `storage.*` | `.native` | Storage services: archive, list, delete, quota checks. |
| `llm.decide_*` | `.ai` | Decision stages for KI-less service nodes. |
| `llm.plan_*` | `.ai` | Orchestrator stages that break a request into a task DAG. |

## Token concept

The relay authenticates nodes and admins with four credential families,
distinguished by their prefixes.

| Prefix | Name | Default TTL | Purpose |
|---|---|---|---|
| `adm_...` | Master admin seed | Until rotated | Bootstrap the cluster and recover admin access |
| `rs_...` | Registration secret | 12 h | Recovery only — rotate the runtime token |
| `tp_...` | Temporary token | 24 h | Issued on registration, replaced after approval |
| `rt_...` | Runtime token | 7 days | Day-to-day Bearer auth for heartbeat, claim, complete |

Human dashboard users log in with a username/password and get a signed session
cookie; they do not use a prefixed token.

### Lifecycle

```
[Register] → temporary token (24h) + registration secret (12h)
       ↓
[Admin approves] → runtime token (7 days), node status: approved
       ↓
[Heartbeat every 8s] → status online → claim → work → complete
       ↓
[Before expiry] → POST /auth/refresh → new runtime token
       ↓
[Lost runtime token] → POST /auth/refresh with registration_secret
                     → new runtime token + new registration secret
```

Key rules:

- **One runtime token per node.** Refreshing it invalidates the previous one.
- **Registration secret is recovery only.** It expires after 12 hours and is
  rotated whenever it is used to recover a runtime token.
- **Master seed is emergency only.** It is only usable for dashboard login
  while no human admin exists or when recovery mode is explicitly enabled.
- **Master seed is created on the relay host.** The HTTP API has no endpoint
  to initialise it, so a network attacker cannot claim the cluster root key.

See [node/token-lifecycle.md](node/token-lifecycle.md) for the full refresh
and recovery flows.

## Node types

The relay distinguishes two broad categories of node.

> **Naming note.** This concept document is written in German-influenced
> style and uses **KI** (German abbreviation for *Künstliche Intelligenz*)
> as the noun for AI. The API reference and code use the English **AI**
> (`/relay/v2`, `.ai` suffix, `chat.ai`). Both terms mean the same thing;
> pick whichever suits your audience. The node types below are sometimes
> called **worker node** (KI-capable / AI-capable) and **service node**
> (KI-less / AI-less) in the docs and dashboard.

### KI-capable nodes

Traditional AI agents. They can:

- Understand natural-language instructions
- Plan multi-step workflows
- Generate content (text, code, images, audio)
- Make judgement calls
- Interact with users

A KI node claims a stage, reads the payload, hands it to its local AI, and
returns the result. The local AI chooses which tools to call and how to
combine them; the node never hard-codes tool calls.

| Capability | Example node | Responsibility |
|---|---|---|
| `chat.ai` | Hermes / assistant node | Conversational interface, general questions |
| `code.ai` | Coding agent node | Write, review, debug code |
| `web.ai` | Research agent node | Search the web, summarise pages |
| `vision.ai` | Vision agent node | Analyse images, describe contents |
| `llm.decide_cleanup.ai` | Storage decision node | Decide which files to delete when quota is hit |
| `llm.plan_task.ai` | Orchestrator node | Break a user request into relay task DAGs |

### KI-less service nodes

Intentionally "dumb" workers. They have no reasoning capability. They:

- Register narrow, well-defined capabilities (`storage.archive`,
  `printer.print`, `switch.toggle`, …)
- Execute only the exact operation described in the stage payload
- Report success or failure with raw data
- **Post decision tasks back to the relay** when a judgement call is needed

| Capability | Node | Responsibility |
|---|---|---|
| `storage.archive` | NAS storage node | Download artifact from relay, write to NAS |
| `storage.list` | NAS storage node | List archived files |
| `storage.delete` | NAS storage node | Delete archived files |
| `storage.quota` | NAS storage node | Report disk usage |
| `backup.snapshot` | NAS backup node | Trigger filesystem snapshots |
| `printer.print` | Printer node | Print documents |
| `switch.toggle` | IoT relay node | Toggle smart-home switches |
| `fs.read`, `fs.write` | File-system node | Read or write local files |
| `camera.capture` | Camera node | Take a photo |

### Why KI-less nodes?

| Benefit | Explanation |
|---|---|
| Safety | A dumb node cannot improvise. It only does what the stage says. |
| Simplicity | Small code base, easy to audit, easy to replace. |
| Reliability | Fewer moving parts, deterministic behaviour. |
| Network placement | Can run on constrained devices (NAS, IoT, Docker). |
| Cost | No GPU or large model required. |

## Self-care pattern

This is the core pattern that connects KI-less nodes to KI-capable nodes
through the relay, without the relay itself having to reason.

> A service node detects a problem it is not allowed to decide itself. Instead
> of making a choice, it creates a task for a KI-capable node.

Example: the storage node notices disk usage above the threshold.

1. Storage node measures disk usage → `0.91`, threshold is `0.85`.
2. Storage node posts a task with a `llm.decide_cleanup` stage.
   Payload: current file list, usage ratio, threshold.
3. A KI node claims the stage, analyses the files, and returns a list of
   candidates to delete.
4. Relay creates a follow-up `storage.delete` stage.
5. Storage node claims and executes the deletion.

No KI logic lives inside the storage node. The relay only routes by
capability; it never interprets the decision.

### Decision boundaries

| Situation | KI node | Service node |
|---|---|---|
| User asks "What should I delete?" | Decide | Measure, then ask |
| Disk full | Analyse and recommend | Report usage, then act on command |
| Image generation | Compose prompt, call worker | Run the model |
| File upload | Trigger upload task | Execute upload |
| Print document | Decide when/where to print | Print the document |
| Trigger backup | Decide if backup needed | Run backup command |

Rule of thumb:

> If the answer to "what should happen next?" requires interpretation,
> preference, or judgement, it belongs to a KI node.
>
> If the answer is deterministic and reversible or explicitly authorised,
> it can belong to a service node.

## Node lifecycle

Every node, regardless of type, follows the same lifecycle:

```
register → poll approval → heartbeat → claim → execute → complete
```

1. **Register** via `POST /relay/v2/auth/register` → receive `node_id`,
   temporary token, and registration secret.
2. **Wait for approval** — an admin activates the node in the dashboard or
   via the admin API. The node polls `/relay/v2/auth/status`.
3. **Heartbeat** every 8 seconds → status moves from `approved` to `online`.
4. **Claim** a stage matching one of its capabilities.
5. **Execute** the action described in the stage payload.
6. **Complete** by submitting the result (or an `error` dict) to the relay.

Node status values:

| Status | Meaning | Set by |
|---|---|---|
| `pending` | Registered, not yet approved | Relay on registration |
| `approved` | Approved, no heartbeat yet | Relay on approval |
| `online` | Sent at least one heartbeat | Relay on heartbeat |
| `offline` | Missed too many heartbeats | Relay watchdog |

`available`, `load`, `queue_depth` in the heartbeat control whether the
scheduler actually sends more work. `online` + `available=false` means
"alive but do not send tasks right now".

## Security model

- **One runtime token per node.** Refreshing it invalidates the previous one.
- **Registration secret is recovery only.** Rotated on every recovery use.
- **Master seed is emergency only.** Created on the relay host, never through
  the HTTP API. Stored as a bcrypt hash; the plain seed is never kept on disk.
- **Core is KI-less.** It routes by capability string; it does not choose
  tools, so it cannot be tricked into running untrusted logic.
- **Service nodes run with minimal privileges** and only touch the paths and
  devices they own.
- **KI nodes validate destructive payloads** before approving them.
- **Unknown capabilities are ignored** — nodes cannot claim work outside
  their role.
- **Keep the relay behind your firewall**; it is designed for private
  networks.
- **Expired tokens are purged hourly by a background watchdog.**

## Glossary

| Term | Meaning |
|---|---|
| **Node** | A process that registers with the relay and advertises capabilities. Either a worker node (KI-capable) or a service node (KI-less). |
| **Capability** | A dot-separated routing key (e.g. `storage.archive.native`) a node advertises; the scheduler matches stages to nodes by exact capability name. |
| **Capability suffix** | `.native` (no AI, runs directly), `.ai` (delegates to local AI), `.relay` (relay-internal). Required on every concrete capability. |
| **Stage** | A single unit of work inside a task DAG. Has a capability, a payload, dependencies, and a status. |
| **Task** | A collection of one or more stages with dependencies, submitted by a node. Has a `task_id` and a priority. |
| **DAG** | Directed acyclic graph of stages within a task; `depends_on` defines the edges. |
| **Heartbeat** | A periodic `POST /relay/v2/discovery/heartbeat` from a node reporting availability, load, queue depth, and current capabilities. Default every 8–10 s. |
| **Claim** | A node takes a pending stage matching one of its capabilities (`POST /relay/v2/scheduler/claim`); the stage becomes `claimed` for up to `claim_ttl_seconds`. |
| **Complete** | A node submits the result of a claimed stage (`POST /relay/v2/scheduler/stages/{id}/complete`). |
| **Runtime token** (`rt_…`) | Day-to-day Bearer token for a node. TTL 7 days, one per node, refreshed via `/auth/refresh`. |
| **Registration secret** (`rs_…`) | Recovery-only credential. TTL 12 h, rotated on every use. Used to recover a lost runtime token. |
| **Temporary token** (`tp_…`) | Short-lived token (24 h) issued on registration, replaced by a runtime token after approval. |
| **Master admin seed** (`adm_…`) | Emergency credential created on the relay host; used to bootstrap the first admin and for recovery. Stored as a bcrypt hash. |
| **Bootstrap seed** (`bs_…`) | One-time 24 h session after a master-seed dashboard login. |
| **SSE** | Server-Sent Events; the relay pushes events to nodes via `GET /relay/v2/events/stream`. |
| **EventBus** | The relay's internal event system; emits typed events (e.g. `board.post_created`, `task.stage_completed`) that nodes subscribe to via SSE. |
| **Self-care pattern** | A KI-less node posts a decision task for a KI node when a judgement call is needed, instead of deciding itself. |
| **Pending / approved / online / offline** | Node status values; see "Node lifecycle". |

## Where to go next

- [server/setup.md](server/setup.md) — install and run the relay server
- [server/admin.md](server/admin.md) — node management and admin API
- [server/dashboard.md](server/dashboard.md) — dashboard usage and approval
- [node/setup.md](node/setup.md) — connect a node from zero to daemon
- [node/token-lifecycle.md](node/token-lifecycle.md) — refresh and recovery
- [node/capabilities.md](node/capabilities.md) — capability profiles
- [reference/api.md](reference/api.md) — full API endpoint table