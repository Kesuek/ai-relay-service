# Federation Node — Concept

> **⚠️ Concept — not yet implemented.** This document describes the planned
> Federation Node based on discussions (2026-08-01). No code exists yet.
> See [IDEAS.md](../../.hermes/projects/ai-relay-service/IDEAS.md) for the
> original idea and [TASKS.md](../../.hermes/projects/ai-relay-service/TASKS.md)
> for the current board state.

## What is a Federation Node?

A **Federation Node** is a node that bridges capabilities between two or more relays. It is not a special node type — it is a normal node that heartbeats the `federation` capability. When connected to a remote relay, it can import remote capabilities and make them available locally, or export local capabilities to the remote relay.

```
┌── Local Relay ──────────────────┐       ┌── Remote Relay ─────────────────┐
│                                  │       │                                  │
│  ┌──────────────────────────┐   │       │   ┌──────────────────────────┐  │
│  │  Federation Node         │──┼───────┼──→│  Federation Node           │  │
│  │  heartbeatet `federation` │   │  P2P  │   │  heartbeatet `federation` │  │
│  │  + subscribed caps       │   │  /HTTP │   │  + exported caps         │  │
│  └──────────────────────────┘   │       │   └──────────────────────────┘  │
│         │                       │       │         │                       │
│    ┌────┴─────┐                 │       │    ┌────┴─────┐                 │
│    │ Tasks    │                 │       │    │ Tasks    │                 │
│    │ forwarded│                 │       │    │ executed │                 │
│    └──────────┘                 │       │    └──────────┘                 │
└──────────────────────────────────┘       └──────────────────────────────────┘
```

## Capability

### `federation`

The Federation Node heartbeats `federation` as its only capability. It does not heartbeat the remote capabilities directly — those are only heartbeated after the local admin approves them via the dashboard.

## How it works

### 1. Connect

The admin sends a task to the Federation Node to establish a connection:

```json
{
  "connect": {
    "url": "https://mac-relay:8788",
    "token": "rt_..."
  }
}
```

The node connects to the remote relay (via P2P or HTTP) and authenticates.

### 2. Discover

Once connected, the node fetches the remote relay's capability list:
```
[mflux.generate, esrgan.upscale, chat.ai]
```

### 3. Dashboard page

The node deploys a dashboard page (via the SSN's `ssn.pages` capability or its own Dynamic Route). The page shows:

- **Status:** Connected / Disconnected
- **Remote relay:** Name + URL
- **Available capabilities:** List with checkboxes
- **Capability translation:** Local name (editable) → Remote name
- **Fair-use limits:** `max_parallel`, `max_daily`
- **Activity log:** Tasks completed, errors, latency

### 4. Admin approves

The admin clicks checkboxes in the dashboard:

```
[x] image.gen.mflux  →  mflux.generate    max_parallel: 2
[ ] image.upscale    →  esrgan.upscale    max_parallel: 1
```

### 5. Node heartbeats approved capabilities

Only after admin approval, the node starts heartbeating the approved capabilities locally. The relay now sees `image.gen.mflux` as a local capability.

### 6. Task forwarding

When a task arrives for `image.gen.mflux`:

1. Federation Node claims the stage
2. Forwards the task to the remote relay via `POST /relay/v2/scheduler/task-simple`
3. Remote relay processes it (its own Federation Node or worker claims it)
4. Result comes back
5. Federation Node completes the stage locally

## Config

```yaml
# ~/.relay/node.yaml (Federation Node)
node_name: federation
description: "Bridge to remote relays"
capabilities:
  - name: federation
    type: native
    claimable: true
    handler: /opt/relay/handlers/federation-handler.sh
    max_parallel: 10
    timeout: 600
    description: "Bridges capabilities from remote relays"
```

## Dashboard page

The dashboard page is hosted by the **SSN** (via `ssn.pages`) or by the Federation Node itself via **Dynamic Routes**. It is an HTMX page that shows:

```
┌─────────────────────────────────────────────┐
│  🌐 Federation — Mac Relay                   │
│  Status: ● Connected  (latency: 12ms)       │
│                                               │
│  Available capabilities:                      │
│                                               │
│  ☑ image.gen.mflux  →  mflux.generate        │
│     max_parallel: 2  │  max_daily: 50        │
│     Tasks today: 12  │  Errors: 0            │
│                                               │
│  ☐ image.upscale  →  esrgan.upscale          │
│     max_parallel: 1  │  max_daily: 20        │
│                                               │
│  [Save]  [Disconnect]                         │
└─────────────────────────────────────────────┘
```

## Multiple remote relays

A single Federation Node can connect to multiple remote relays. Each connection has its own dashboard card:

```
┌── Federation ──────────────────────────────┐
│                                              │
│  ┌── Mac Relay ──────────────────────────┐  │
│  │  ● Connected  │  ☑ image.gen.mflux    │  │
│  └────────────────────────────────────────┘  │
│                                              │
│  ┌── Community Relay ─────────────────────┐  │
│  │  ● Connected  │  ☐ llm.chat           │  │
│  │               │  ☐ web.ai             │  │
│  └────────────────────────────────────────┘  │
│                                              │
│  ┌── Friend's 4090 ───────────────────────┐  │
│  │  ○ Disconnected                        │  │
│  └────────────────────────────────────────┘  │
└──────────────────────────────────────────────┘
```

## Transport

The Federation Node handles transport internally. The relay never sees it:

| Scenario | Transport | NAT |
|----------|-----------|-----|
| **LAN** | Direct HTTP/HTTPS | No NAT |
| **Internet** | P2P (QUIC or WebRTC) | NAT-traversal, no port forwarding |
| **Fallback** | Relay server (like Syncthing) | When P2P doesn't connect |

## Key properties

- **No relay code changes** — Federation is pure node code
- **Federation is a capability** — the node heartbeats `federation`, nothing else
- **Admin controls what gets heartbeated** — no capability is advertised without dashboard approval
- **Capability translation** — local name ≠ remote name (admin sets the local name)
- **Multiple remote relays** — one Federation Node, many connections
- **One hop** — the node forwards directly to the target relay, no chain
- **Fair use** — `max_parallel`, `max_daily` as policy mechanism, no money
- **Temporary bridges** — connect, use, disconnect. No permanent setup needed

## What the Federation Node needs (node code, no relay code)

- `nodes/common/federation_node.py` — Daemon (connection, dashboard page, claim, forward)
- `federation` handler — accepts `connect` task, establishes connection
- Dashboard HTML (capability page or Dynamic Route) — shows remote capabilities, checkboxes, status
- P2P transport (QUIC/WebRTC) — NAT traversal, no port forwarding
- Task forward: `POST /relay/v2/scheduler/task-simple` to remote relay
- Result forward: result back → stage complete
- Nothing that isn't already in the `node-cli` framework (RelayClient, heartbeat, claim, complete, capability pages)

## See also

- **[concept.md](concept.md)** — what a node is
- **[capability-concept.md](capability-concept.md)** — what a capability is
- **[capabilities.md](capabilities.md)** — capability reference, naming, handler contract
- **[ssn.md](ssn.md)** — SSN implementation (hosts the federation dashboard page)
- **[node-config.md](node-config.md)** — `node.yaml` format
