# Node Concept

## What is a Node?

A **node** is a process that connects to the relay, heartbeats its presence, and optionally offers capabilities. Every node is identical in its core behaviour — there is only one node type. What makes a node useful are the **capabilities** it heartbeats.

```
┌─────────────────────────────────────────────┐
│  Node                                        │
│                                              │
│  ┌──────────────────────────────────────┐  │
│  │  Core (every node)                     │  │
│  │  ─────────────────                    │  │
│  │  • Register with the relay            │  │
│  │  • Heartbeat presence + status        │  │
│  │  • Manage token lifecycle             │  │
│  │  • Claim + complete tasks             │  │
│  └──────────────────────────────────────┘  │
│                                              │
│  ┌──────────────────────────────────────┐  │
│  │  Capabilities (optional)             │  │
│  │  ──────────────────────              │  │
│  │  • chat.ai          → LLM chat       │  │
│  │  • image.gen.mflux  → image gen      │  │
│  │  • ssn.pages        → host pages     │  │
│  │  • federation       → bridge relays  │  │
│  └──────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
```

## What every node does

### 1. Register

A node registers with the relay once. It receives:
- A **node ID** (8-char base32, e.g. `3P4KEWGE`)
- A **temporary token** for the first heartbeat
- A **registration secret** for token recovery

After registration, the node must be **approved** by an admin before it can claim tasks.

### 2. Heartbeat

Every node sends a heartbeat to the relay at a regular interval (default 8s). The heartbeat contains:
- **Status** — `online`, `busy`, `idle`, `maintenance`
- **Load** — CPU load normalised to 0–100
- **Capabilities** — what this node can do (see below)
- **Node name + description** — human-readable metadata

The relay uses heartbeats to track which nodes are alive. A node that misses 3 heartbeats is marked `offline`.

### 3. Manage tokens

Every node has a **runtime token** (`rt_...`) that expires after a configurable period (default 7 days). The node must refresh it proactively before expiry. If the token expires, the node can recover using its registration secret.

### 4. Claim and complete tasks

When a node heartbeats a capability, the relay may assign it tasks for that capability. The node:
1. **Claims** the next pending stage for its capabilities
2. **Executes** the task (runs a handler, calls an API, generates an image, etc.)
3. **Completes** the stage with a result (or marks it as failed)

This is the same for every node — regardless of what capability it offers.

## What makes nodes different: Capabilities

A node without capabilities is just a heartbeat — present but idle. Capabilities define what a node can actually **do**. A node can heartbeat any number of capabilities, and it can change them at runtime.

Common capability patterns:

| Capability | What the node does | Example node |
|-----------|-------------------|-------------|
| `chat.ai` | Runs an LLM to answer chat requests | Worker on Mac mini |
| `image.generate.mflux` | Generates images via FLUX | Worker on Mac mini |
| `ssn.pages` | Hosts HTML dashboard pages for other nodes | SSN on relay host |
| `ssn.proxy` | Provides API proxy endpoints for dashboard pages | SSN on relay host |
| `federation` | Bridges capabilities from remote relays | Federation node |

A node can heartbeat multiple capabilities at once. The same physical machine can run multiple nodes, each with different capabilities.

## Node lifecycle

```
[Register] → [Pending] → [Approved] → [Online] → [Offline]
                │              │            │
                │         ┌────┘            │
                │         ▼                 │
                │    [Approved →            │
                │     heartbeats,           │
                │     no tasks yet]         │
                │                           │
                └── [Never approved →      │
                     deleted after TTL]     │
                                            │
                                     [Busy / Idle]
                                      (runtime status)
```

## What a node is NOT

- **Not a machine** — a single host can run many nodes
- **Not a process type** — there is no "worker node" vs "SSN" vs "federation node". There is only **node**.
- **Not tied to a capability** — a node can change its capabilities at any time
- **Not a relay** — a node connects to a relay, it does not route tasks itself
