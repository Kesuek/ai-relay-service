# Relay — Concepts

This document is the central concept reference for the AI Relay Service. It
explains what the relay is, the architecture it follows, how capabilities and
tokens work, and the self-care pattern that ties them together. All other
documents link back here for the underlying mental model.

> **New to the relay?** Start with [getting-started.md](getting-started.md) for
> a scenario-based introduction, then read [node/concept.md](node/concept.md)
> (what a node is) and [node/capability-concept.md](node/capability-concept.md)
> (what a capability is) before diving into this reference.

## What is the Relay?

The Relay is a **coordination layer** for a cluster of distributed worker
nodes. It does one thing well: it connects, authenticates, distributes tasks,
and monitors availability. It never runs domain logic itself.

- It owns the registry, heartbeat state, the task DAG, and the event stream.
- It routes work by **capability string** — it does not choose tools, models,
  or parameters.
- Every domain service (Board, Vault, Storage, …) and every worker runs as
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
  ┌──────────────────────────────────────────────────────────────────────┐
  │  Node (one type, differentiated by capabilities)                     │
  │                                                                      │
  │  • chat.ai          → LLM chat          (worker on Mac)             │
  │  • image.gen.mflux  → image generation  (worker on Mac)             │
  │  • ssn.pages        → host dashboard    (SSN on relay host)        │
  │  • federation       → bridge relays     (federation node)          │
  └──────────────────────────────────────────────────────────────────────┘
```

## Capability concept

Capabilities are the **routing keys** the relay uses to match stages to nodes.
For a full introduction see [node/capability-concept.md](node/capability-concept.md).

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
|--------|---------|---------|
| `.native` | Runs on the node directly. No external reasoning. | `storage.archive.native`, `db.board.create.native` |
| `.ai` | Delegates to a local AI or LLM for reasoning. | `chat.ai`, `code.ai` |
| `.relay` | Relay-internal orchestration capability. | `llm.decide_cleanup.relay` |

> **Nodes without local AI use `.native`.** A database service node
> advertises `db.board.create.native`, `db.post.read.native`, etc. — never
> the bare `db.board.create`. The relay matches names **exactly**, so a
> stage requesting `db.board.create.native` will not be claimed by a node
> that only advertised `db.board.create`.

### Core capability names

To keep clusters interoperable, the ecosystem recommends a small set of core
names. Use these names when they fit; you may register domain-specific names
(e.g. `printer.a4.native`) if the core names do not cover your use case.

| Core name | Typical mode | Meaning |
|-----------|-------------|---------|
| `chat` | `.ai` | Conversational agent. Answers questions, reasons, interacts with users. |
| `code` | `.ai` | Coding agent. Writes, reviews, debugs code. |
| `web` | `.ai` | Research agent. Searches the web, summarises pages. |
| `vision` | `.ai` | Vision agent. Analyses images, describes contents. |
| `terminal` | `.native` or `.ai` | Executes shell commands, directly or after local AI confirmation. |
| `file` | `.native` | Filesystem operations: read, write, move, delete. |
| `storage.*` | `.native` | Storage services: archive, list, delete, quota checks. |
| `llm.decide_*` | `.ai` | Decision stages for nodes without reasoning. |
| `llm.plan_*` | `.ai` | Orchestrator stages that break a request into a task DAG. |

For the full capability reference (handler contract, Dynamic Routes, validation,
metadata forwarding) see [node/capabilities.md](node/capabilities.md).

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
[Register] → temporary token (24h) + registration secret (7 days)
       ↓
[Admin approves] → runtime token (7 days), node status: approved
       ↓
[Heartbeat every 8 s (default)] → status online → claim → work → complete
       ↓
[Before expiry] → POST /auth/refresh → new runtime token
       ↓
[Lost runtime token] → POST /auth/refresh with registration_secret
                     → new runtime token + new registration secret
```

Key rules:

- **One runtime token per node.** Refreshing it invalidates the previous one.
- **Registration secret is recovery only.** It expires after 7 days (168h, matching the runtime token TTL) and is
  rotated whenever it is used to recover a runtime token.
- **Master seed is emergency only.** It is only usable for dashboard login
  while no human admin exists or when recovery mode is explicitly enabled.
- **Master seed is created on the relay host.** The HTTP API has no endpoint
  to initialise it, so a network attacker cannot claim the cluster root key.

See [node/token-lifecycle.md](node/token-lifecycle.md) for the full refresh
and recovery flows.

## Node concept

A **node** is a process that connects to the relay, heartbeats its presence, and
offers capabilities. There is only one node type — what makes a node useful are
the **capabilities** it heartbeats.

For a full introduction see [node/concept.md](node/concept.md).

### Common capability patterns

| Capability | What the node does | Example node | Documentation |
|-----------|-------------------|-------------|---------------|
| `chat.ai` | Runs an LLM to answer chat requests | Worker on Mac mini | [capabilities.md](node/capabilities.md) |
| `image.generate.mflux` | Generates images via FLUX | Worker on Mac mini | [capabilities.md](node/capabilities.md) |
| `ssn.pages` + `ssn.proxy` | Hosts dashboard pages + API proxy | SSN on relay host | [ssn.md](node/ssn.md) |
| `federation` | Bridges capabilities from remote relays | Federation node | [federation.md](node/federation.md) |

### Capability execution modes

While there is only one node type, capabilities fall into two broad categories
based on how they execute work:

| | With reasoning (`.ai`) | Without reasoning (`.native`) |
|---|---|---|
| **Behaviour** | Understands natural language, plans, judges | Executes exactly what the stage says |
| **Example** | `chat.ai`, `code.ai`, `web.ai` | `storage.archive.native`, `db.board.create.native` |
| **Safety** | Validates destructive payloads before approving | Cannot improvise — only does what the stage says |
| **Cost** | Needs GPU or large model | Runs on constrained devices (NAS, IoT, Docker) |

### Self-care pattern

This is the core pattern that connects capabilities without reasoning to
capabilities with reasoning through the relay, without the relay itself
having to decide.

> A node detects a problem it is not allowed to decide itself. Instead
> of making a choice, it creates a task for a capability that can reason
> about it.

Example: the storage node notices disk usage above the threshold.

1. Storage node measures disk usage → `0.91`, threshold is `0.85`.
2. Storage node posts a task with a `llm.decide_cleanup` stage.
   Payload: current file list, usage ratio, threshold.
3. A node with `llm.decide_cleanup.ai` claims the stage, analyses the files,
   and returns a list of candidates to delete.
4. Relay creates a follow-up `storage.delete` stage.
5. Storage node claims and executes the deletion.

No decision logic lives inside the storage node. The relay only routes by
capability; it never interprets the decision.

### Decision boundaries

| Situation | With reasoning (`.ai`) | Without reasoning (`.native`) |
|-----------|----------------|--------------|
| User asks "What should I delete?" | Decide | Measure, then ask |
| Disk full | Analyse and recommend | Report usage, then act on command |
| Image generation | Compose prompt, call worker | Run the model |
| File upload | Trigger upload task | Execute upload |
| Print document | Decide when/where to print | Print the document |
| Trigger backup | Decide if backup needed | Run backup command |

Rule of thumb:

> If the answer to "what should happen next?" requires interpretation,
> preference, or judgement, it belongs to a capability with reasoning (`.ai`).
>
> If the answer is deterministic and reversible or explicitly authorised,
> it can belong to a capability without reasoning (`.native`).

### Why capabilities without reasoning?

| Benefit | Explanation |
|---------|-------------|
| Safety | A node without reasoning cannot improvise. It only does what the stage says. |
| Simplicity | Small code base, easy to audit, easy to replace. |
| Reliability | Fewer moving parts, deterministic behaviour. |
| Network placement | Can run on constrained devices (NAS, IoT, Docker). |
| Cost | No GPU or large model required. |

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

| Status | Category | Meaning | Set by |
|---|---|---|---|
| `pending` | PENDING | Registered, not yet approved | Relay on registration |
| `approved` | AVAILABLE | Approved, no heartbeat yet | Relay on approval |
| `online` | AVAILABLE | Sent at least one heartbeat | Relay on heartbeat |
| `idle` | AVAILABLE | Online and explicitly available for claims | `node-cli node idle` / auto-revert from busy |
| `busy` | BUSY | Online but not accepting new claims | `node-cli node busy` / auto-busy on sustained load |
| `maintenance` | BUSY | Manually taken out of rotation | Operator (future) |
| `offline` | OFFLINE | Missed too many heartbeats | Relay watchdog |

`available`, `load`, `queue_depth` in the heartbeat control whether the
scheduler actually sends more work. `online` + `available=false` means
"alive but do not send tasks right now".

> **Scaling note:** The relay is designed for single-server, small-to-medium
> clusters — tens of nodes and hundreds of tasks per minute. SQLite with WAL
> handles this comfortably. For larger deployments (hundreds of nodes, very
> high throughput), see [server/setup.md](server/setup.md) for scaling
> considerations.

## Status system (Phase 18)

All entity statuses — nodes, tasks, stages and users — are defined in
a single central registry at `src/relay_server/core/status.py`. The
registry maps each status name to a **category** and a list of allowed
transitions. Business logic (scheduler, discovery watchdog, dashboard)
queries by category instead of hardcoded string lists, so new status
values can be added without touching call sites.

### Categories

| Category | Meaning | Typical statuses |
|---|---|---|
| `AVAILABLE` | Online and ready to accept work | `approved`, `online`, `idle`, `active` |
| `BUSY` | Online but currently cannot accept work | `busy`, `running`, `claimed`, `maintenance` |
| `PENDING` | Waiting for a decision / input / approval | `pending`, `accepted`, `awaiting_subtasks`, `needs_input` |
| `TERMINAL` | Final state, no further transitions | `completed`, `failed`, `timed_out`, `cancelled` |
| `OFFLINE` | Not reachable | `offline`, `inactive` |

Helper predicates: `is_terminal()`, `is_busy()`, `is_available()`,
`is_pending()`, `is_offline()`, `get_category()`. For node-specific
reasoning use `node_can_claim()` (AVAILABLE only) and
`node_is_claimable()` (AVAILABLE + PENDING).

### Transitions

Because status names overlap across entity types (`pending` exists for
nodes, tasks and stages with different allowed transitions), transition
checks are entity-specific: `node_can_transition()`,
`task_can_transition()`, `stage_can_transition()`, `user_can_transition()`
(or `can_transition(from, to, entity_type=...)`).

```
Node:     offline → pending → approved → online ⇄ busy ⇄ idle
                                          ↓        ↓
                                       offline  offline

Task:     pending → accepted → running → completed/failed/timed_out/cancelled
                              ↑↓
                  awaiting_subtasks / needs_input

Stage:    pending → claimed → completed/failed/timed_out
                  ↑↓           pending (released back)
```

### Busy mode (manual + auto)

A node can be marked `busy` manually with `node-cli node busy` (and
reverted with `node-cli node idle` or `node-cli node clear-status`).
The request persists in `ai-relay-agent.json` and is forwarded on the
next heartbeat; the server validates the transition via the central
registry and silently ignores invalid ones.

Automatic busy: when a node's `load` stays at or above its `load_cap`
for `auto_busy_consecutive_heartbeats` (default 3) heartbeats in a row,
the server transitions the node to `busy` and stops it from claiming new
stages. As soon as the load drops back below the cap, the node reverts
to `idle` automatically. The `consecutive_high_load` counter is stored
per node and resets to 0 on every below-cap heartbeat.

**GPU-aware auto-busy (T-113):** in addition to the load-based rule, a
node with `queue_depth >= 1` (i.e. it already has a task in flight) is
transitioned to `busy` immediately, regardless of its CPU `load`. This
handles AI/ML workloads where the GPU is saturated but the CPU is idle —
a node running one FLUX/MLX job must not be handed a second job just
because its CPU load is low. The node reverts to `idle` when the queue
drains (`queue_depth == 0`) *and* load is below the cap (so a
load-busy node is not prematurely released).

### `status_changed` SSE event

Every status transition publishes a `status_changed` event on the event
bus (and thus the SSE stream) with the payload:

```json
{
  "entity_type": "node" | "task" | "stage" | "user",
  "entity_id": "...",
  "old_status": "..." | null,
  "new_status": "..."
}
```

Subscribers can filter on `event_types: ["status_changed"]` to receive
only status transitions. The event is fired for explicit requests
(`node-cli node busy`), auto-busy, the offline watchdog, and every
scheduler stage/task transition (claim, complete, fail, time out).

## Database backends (T-110)

The relay stores all of its state in a relational database. SQLite is the
default — a single file at `~/.relay/server.db` — and requires no external
server. Since T-110 the database layer is built on **SQLAlchemy Core**, so
the same code runs unchanged on PostgreSQL as well: switching backends is a
config change, not a code change.

- **SQLite (default):** `db_type: sqlite`, `db_path: ~/.relay/server.db`.
  The on-disk file is identical to what the legacy raw-`sqlite3` code
  produced; the switch to a SQLAlchemy engine is transparent.
- **PostgreSQL (opt-in):** `db_type: postgres`,
  `pg_dsn: postgresql+psycopg://user:pass@host:5432/relay`. Install the
  `[postgres]` extra. Connection pooling with `pool_pre_ping` is built in.
- **MariaDB / MySQL:** stub retained; implementation deferred.

Schema, queries and migrations are dialect-independent. The schema lives
as portable `sa.Table` objects in `core/tables.py`; queries use the `q()`
helper which rewrites SQLite `?` placeholders to the dialect-appropriate
form. Timestamps remain ISO-8601 TEXT strings (the existing SQLite DB
stays byte-identical). See [reference/database-backends.md](reference/database-backends.md)
for the full guide, including how to add a new backend.

## Observability (T-109)

The relay is observable through three built-in surfaces, all implemented
without external dependencies (no Prometheus server, no Grafana):

- **`/metrics`** (root, no auth) — Prometheus exposition text. Scrapes
  in-process counters (`relay_auth_failures_total{endpoint="..."}`) and
  DB-derived gauges (`relay_nodes_total`, `relay_nodes_online`,
  `relay_queue_depth`, `relay_tasks{status="..."}`,
  `relay_stages{status="..."}`). A future Prometheus server can scrape
  it without any code change.
- **`/ready`** (root, no auth) — readiness check. Probes the database
  (`SELECT 1`), the maintenance loop age (`maintenance_age_seconds`,
  freshly stamped by `_maintenance_loop`) and the event bus. Returns
  `{"status": "ready"|"degraded", "database", "scheduler", "event_bus",
  "maintenance_age_seconds"}`.
- **Built-in metrics dashboard** at `/relay/v2/dashboard/metrics`
  (session auth) — renders the same data as cards and minimal bar
  charts. JSON backing API: `/relay/v2/dashboard/api/metrics`.

Auth failures (HTTP 401/403/429) are counted globally by a middleware
without touching `auth.py`. `/metrics` and `/ready` are intentionally
open — like `/health` — because the output carries no secrets
(Homelab-Pragmatism).

### Structured JSON logs

Logging uses a small JSON formatter (`core/logging_setup.py`) on the
standard `logging` module — one JSON object per line with `ts`,
`level`, `logger`, `msg`, `trace_id`. A middleware sets a per-request
`trace_id` (16-hex) via `contextvars` and echoes it back as the
`X-Relay-Trace-Id` response header. The same `trace_id` appears in
every log line of that request, so a single failing request can be
filtered with `grep "<trace_id>"` in the journal.

## Security model

- **One runtime token per node.** Refreshing it invalidates the previous one.
- **Registration secret is recovery only.** Rotated on every recovery use.
- **Master seed is emergency only.** Created on the relay host, never through
  the HTTP API. Stored as a bcrypt hash; the plain seed is never kept on disk.
- **The core routes tasks by capability string.** It does not choose tools, so it cannot
  be tricked into running untrusted logic.
- **Nodes run with minimal privileges** and only touch the paths and
  devices they own.
- **Nodes with reasoning validate destructive payloads** before approving them.
- **Unknown capabilities are ignored** — nodes cannot claim work outside
  their role.
- **Keep the relay behind your firewall**; it is designed for private
  networks.
- **Expired tokens are purged hourly by a background watchdog.**

## Glossary

| Term | Meaning |
|---|---|
| **Node** | A process that registers with the relay and heartbeats capabilities. There is one node type — capabilities define what it does. See [node/concept.md](node/concept.md). |
| **Capability** | A dot-separated routing key (e.g. `storage.archive.native`) a node advertises; the scheduler matches stages to nodes by exact capability name. See [node/capability-concept.md](node/capability-concept.md). |
| **Capability suffix** | `.native` (no AI, runs directly), `.ai` (delegates to local AI), `.relay` (relay-internal). Required on every concrete capability. See [node/capabilities.md](node/capabilities.md). |
| **Stage** | A single unit of work inside a task DAG. Has a capability, a payload, dependencies, and a status. |
| **Task** | A collection of one or more stages with dependencies, submitted by a node. Has a `task_id` and a priority. |
| **DAG** | Directed acyclic graph of stages within a task; `depends_on` defines the edges. |
| **Heartbeat** | A periodic `POST /relay/v2/discovery/heartbeat` from a node reporting availability, load, queue depth, and current capabilities. Default every 8 s (configurable via `heartbeat_interval_seconds`). |
| **Claim** | A node takes a pending stage matching one of its capabilities (`POST /relay/v2/scheduler/claim`); the stage becomes `claimed` for up to `claim_ttl_seconds`. |
| **Complete** | A node submits the result of a claimed stage (`POST /relay/v2/scheduler/stages/{id}/complete`). |
| **Runtime token** (`rt_…`) | Day-to-day Bearer token for a node. TTL 7 days, one per node, refreshed via `/auth/refresh`. See [node/token-lifecycle.md](node/token-lifecycle.md). |
| **Registration secret** (`rs_…`) | Recovery-only credential. TTL 12 h, rotated on every use. Used to recover a lost runtime token. |
| **Temporary token** (`tp_…`) | Short-lived token (24 h) issued on registration, replaced by a runtime token after approval. |
| **Master admin seed** (`adm_…`) | Emergency credential created on the relay host; used to bootstrap the first admin and for recovery. Stored as a bcrypt hash. |
| **Bootstrap seed** (`bs_…`) | One-time 24 h session after a master-seed dashboard login. |
| **SSE** | Server-Sent Events; the relay pushes events to nodes via `GET /relay/v2/events/stream`. |
| **EventBus** | The relay's internal event system; emits typed events (e.g. `board.post_created`, `task.stage_completed`) that nodes subscribe to via SSE. |
| **Self-care pattern** | A node without reasoning posts a decision task for a capability with reasoning when a judgement call is needed, instead of deciding itself. |
| **SSN** | A node that runs on the relay host and heartbeats `ssn.pages` + `ssn.proxy`. See [node/ssn.md](node/ssn.md). |
| **Federation Node** | A node that heartbeats `federation` and bridges capabilities from remote relays. See [node/federation.md](node/federation.md). |
| **Pending / approved / online / offline** | Node status values; see "Node lifecycle" above. |

## Where to go next

- [server/setup.md](server/setup.md) — install and run the relay server
- [server/admin.md](server/admin.md) — node management and admin API
- [server/dashboard.md](server/dashboard.md) — dashboard usage and approval
- [node/setup.md](node/setup.md) — connect a node from zero to daemon
- [node/token-lifecycle.md](node/token-lifecycle.md) — refresh and recovery
- [node/capabilities.md](node/capabilities.md) — capability profiles
- [reference/api.md](reference/api.md) — full API endpoint table