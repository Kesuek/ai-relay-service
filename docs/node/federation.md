# Federation Node — Concept

> **⚠️ Concept — not yet implemented.** This document describes the planned
> Federation Node based on discussions (2026-08-01) and subsequent design
> refinements (2026-08-03). No code exists yet.
> See [IDEAS.md](../../.hermes/projects/ai-relay-service/IDEAS.md) for the
> original idea and [TASKS.md](../../.hermes/projects/ai-relay-service/TASKS.md)
> for the current board state.

## What is a Federation Node?

A **Federation Node** is a node that bridges capabilities between two or more
relays. It is not a special node type — it is a normal node that heartbeats the
`federation` capability. When connected to a remote relay, it can import remote
capabilities and make them available locally, or export local capabilities to
the remote relay.

```
┌── Local Relay ──────────────────┐       ┌── Remote Relay ─────────────────┐
│                                  │       │                                  │
│  ┌──────────────────────────┐   │       │   ┌──────────────────────────┐  │
│  │  Federation Node         │──┼───────┼──→│  Federation Node           │  │
│  │  heartbeatet `federation` │   │transport│   │  heartbeatet `federation` │  │
│  │  + subscribed caps       │   │  (HTTP  │   │  + exported caps         │  │
│  └──────────────────────────┘   │   /email │   └──────────────────────────┘  │
│         │                       │   /P2P)  │         │                       │
│    ┌────┴─────┐                 │       │    ┌────┴─────┐                 │
│    │ Tasks    │                 │       │    │ Tasks    │                 │
│    │ forwarded│                 │       │    │ executed │                 │
│    └──────────┘                 │       │    └──────────┘                 │
└──────────────────────────────────┘       └──────────────────────────────────┘
```

## Core architecture: Inbox/Outbox + transport-agnostic node

The Federation Node is built on the **Inbox/Outbox message pattern** (the same
pattern proven in the Hermes Gateway Bridge Adapter). The node itself is
**fully transport-agnostic** — it only reads and writes files. The concrete
transport (HTTP, E-Mail, P2P) is handled by a swappable **Transport wrapper**,
the only component that touches the network.

```
┌─────────────────────────────────────────────────────────┐
│  Federation Node (transport-agnostic)                    │
│  • heartbeats `federation` + approved caps locally        │
│  • claims stage → writes forward file to outbox/          │
│  • polls inbox/ → completes stage locally                 │
│  • NO network access, NO remote_task_id knowledge         │
└───────────────────────┬─────────────────────────────────┘
                        │ file only
┌───────────────────────┴─────────────────────────────────┐
│  Transport wrapper (the ONLY network component)          │
│  • knows HTTP / E-Mail / P2P                             │
│  • translates file ↔ transport                           │
│  • carries remote_task_id ↔ local stage mapping          │
└──────────────────────────────────────────────────────────┘
        ┌───────────────┬───────────────┬───────────────┐
   transport_type:   http           email          p2p
```

### Key properties

- **The wrapper is the only component that knows the transport.** The node,
  handler and dashboard never see a socket — they only read/write JSON files
  in `inbox/`/`outbox/`.
- **New transport = a new wrapper class.** HTTP, E-Mail and P2P are all
  interchangeable backends behind the same `create_transport()` factory,
  selected by `transport_type` in the node config. No system change.
- **Crash-safe by design.** A task is a file. If the connection drops, the
  file stays in `outbox/` and the wrapper simply re-syncs when the connection
  returns. Nothing is lost.
- **Async by nature.** The two relays do not need to be online at the same
  time — the transport (especially E-Mail) buffers until both sides are ready.

### Directory layout (per remote connection)

```
~/.relay/federation/<remote-relay-name>/
├── inbox/      # results from remote relay → node processes → completes stage
└── outbox/     # task forwards → wrapper syncs out
```

## Transport abstraction

The `Transport` interface mirrors the pluggable database abstraction in the
server (`core/db.py`): a `Database` protocol → `create_database()` factory on
`db_type`. Here it is a `Transport` protocol → `create_transport()` factory on
`transport_type`.

```python
# nodes/common/federation/transport.py
class Transport:
    """Pluggable federation transport backend.

    The only component that touches the network. Translates files in
    inbox/outbox into transport calls (HTTP, E-Mail, P2P). Carries the
    remote_task_id ↔ local stage mapping. A new transport = new class +
    factory entry + config line — no node changes.
    """

    def connect(self, url: str, token: str) -> None:
        """Establish a session to the remote relay. Raise on failure."""
        raise NotImplementedError

    def sync_outbox(self, outbox_dir: Path) -> list[str]:
        """Send pending outbox task files to the remote. Return ids sent."""
        raise NotImplementedError

    def sync_inbox(self, inbox_dir: Path) -> list[str]:
        """Fetch remote results, write them as inbox files. Return new ids."""
        raise NotImplementedError

    def discover_capabilities(self) -> list[dict[str, Any]]:
        """Return the remote relay's advertised capabilities (for approval)."""
        raise NotImplementedError

    def close(self) -> None:
        """Release resources. No-op by default."""
        pass


def create_transport(cfg: dict[str, Any]) -> Transport:
    transport_type = cfg.get("federation.transport_type", "http")
    if transport_type == "http":
        from nodes.common.federation.transports.http_transport import HttpTransport
        return HttpTransport(cfg)
    # if transport_type == "email":   # T-100
    #     from ...email_transport import EmailTransport
    #     return EmailTransport(cfg)
    # if transport_type == "p2p":     # later, optional
    #     from ...p2p_transport import P2pTransport
    #     return P2pTransport(cfg)
    raise ValueError(f"Unknown transport_type: {transport_type!r}")
```

### Transport backends

| `transport_type` | Backend | Use case | NAT |
|------------------|---------|----------|-----|
| `http` | **HTTP/HTTPS (V1, default)** — `POST /relay/v2/scheduler/task-simple`, poll `/relay/v2/scheduler/tasks/{id}` | Fast LAN / Tailscale | Tailscale or reachable host |
| `email` | **E-Mail** — himalaya + IMAP-IDLE watcher, Task JSON in mail body, `fed_<id>` subject | Universal fallback, relays that are not both online | None (works everywhere) |
| `p2p` | **P2P (QUIC/WebRTC)** — later, optional | Fully decentralized, no reachable host | NAT-traversal, no port forwarding |

The `email` backend is the natural universal fallback: E-Mail is itself an
asynchronous message queue, so the Inbox/Outbox pattern maps directly onto it.
`sync_outbox()` sends task files as mails; `sync_inbox()` (via an existing
IMAP-IDLE watcher) turns incoming federation mails into inbox files. A
dedicated mailbox/IMAP folder per remote relay handles addressing.

## Capability

### `federation`

The Federation Node heartbeats `federation` as its only capability. It does not
heartbeat the remote capabilities directly — those are only heartbeated after
the local admin approves them via the dashboard.

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

The node builds a transport via `create_transport(cfg)` and connects.

### 2. Discover

Once connected, the transport fetches the remote relay's capability list via
`discover_capabilities()`:
```
[mflux.generate, esrgan.upscale, chat.ai]
```

### 3. Dashboard page

The node deploys a dashboard page (via the SSN's `ssn.pages` capability or its
own Dynamic Route). The page shows:

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

Only after admin approval, the node starts heartbeating the approved
capabilities locally. The relay now sees `image.gen.mflux` as a local
capability.

### 6. Task forwarding

When a task arrives for `image.gen.mflux`:

1. Federation Node claims the stage
2. Node writes a forward file to `outbox/<remote>/`
3. Transport `sync_outbox()` sends it to the remote relay
   (`POST /relay/v2/scheduler/task-simple`)
4. Remote relay processes it (its own Federation Node or worker claims it)
5. Transport `sync_inbox()` fetches the result, writes it as an inbox file
6. Node reads the inbox file, completes the stage locally

## Config

```yaml
# ~/.relay/node.yaml (Federation Node)
node_name: federation
description: "Bridge to remote relays"
federation:
  transport_type: http        # http | email | p2p
  remote_relay:
    url: "https://mac-relay:8788"
    token: "rt_..."           # runtime token of the REMOTE relay
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

The dashboard page is hosted by the **SSN** (via `ssn.pages`) or by the
Federation Node itself via **Dynamic Routes**. It is an HTMX page that shows:

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

A single Federation Node can connect to multiple remote relays. Each connection
has its own transport instance (via `create_transport()`) and its own
inbox/outbox directory. Each connection has its own dashboard card:

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

## Key properties

- **No relay code changes** — Federation is pure node code
- **Federation is a capability** — the node heartbeats `federation`, nothing else
- **Transport-agnostic node** — the node only reads/writes inbox/outbox files
- **Swappable transport** — HTTP / E-Mail / P2P via `create_transport()` factory
- **Crash-safe** — tasks are files; a dropped connection loses nothing
- **Admin controls what gets heartbeated** — no capability is advertised without dashboard approval
- **Capability translation** — local name ≠ remote name (admin sets the local name)
- **Multiple remote relays** — one Federation Node, many connections, one transport each
- **One hop** — the node forwards directly to the target relay, no chain
- **Fair use** — `max_parallel`, `max_daily` as policy mechanism, no money
- **Temporary bridges** — connect, use, disconnect. No permanent setup needed

## What the Federation Node needs (node code, no relay code)

- `nodes/common/federation/transport.py` — `Transport` protocol + `create_transport()` factory
- `nodes/common/federation/transports/http_transport.py` — HTTP backend (V1)
- `nodes/common/federation/transports/email_transport.py` — E-Mail backend (T-100)
- `nodes/common/federation/federation_node.py` — Daemon (claim, forward, complete; inbox/outbox processing)
- `federation` handler — accepts `connect` task, establishes connection
- Dashboard HTML (capability page or Dynamic Route) — shows remote capabilities, checkboxes, status
- Fair-use policy — `max_parallel`, `max_daily` enforcement in the daemon

## See also

- **[concept.md](concept.md)** — what a node is
- **[capability-concept.md](capability-concept.md)** — what a capability is
- **[capabilities.md](capabilities.md)** — capability reference, naming, handler contract
- **[ssn.md](ssn.md)** — SSN implementation (hosts the federation dashboard page)
- **[node-config.md](node-config.md)** — `node.yaml` format
- **Inbox/Outbox pattern** — inspired by the Hermes Gateway Bridge Adapter
- **Pluggable backend pattern** — mirrors `core/db.py` (`Database` → `create_database()`)
