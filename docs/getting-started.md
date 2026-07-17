# Getting Started

Pick the scenario that matches what you want to do. Each path links to the
detailed guide you need — you do not have to read everything.

## 1. I just want to run a node

A relay is already running somewhere on your network and you want to connect
a worker or service node to it.

→ **[node/setup.md](node/setup.md)** — register the node, get approved,
  publish a capability profile, start the daemon.
→ **[node/token-lifecycle.md](node/token-lifecycle.md)** — keep tokens
  fresh.
→ **[node/capabilities.md](node/capabilities.md)** — define what the node
  can do.

You do **not** need the server guides for this path.

## 2. I want a relay + one node (single-host cluster)

You are setting up the whole thing on one machine (or one relay + one node
on the same LAN).

1. → **[server/setup.md](server/setup.md)** — install the relay, create the
   master seed, bootstrap the first admin, start the server.
2. → **[server/admin.md](server/admin.md)** — approve the node once it has
   registered.
3. → **[node/setup.md](node/setup.md)** — register the node, start the
   daemon.
4. → **[concepts.md](concepts.md)** — read this once to understand the
   mental model.

## 3. I want a multi-node cluster

You are building a real cluster: one relay, several nodes (workers +
service nodes), possibly across hosts or containers.

1. → **[server/setup.md](server/setup.md)** — relay install, HTTPS via a
   reverse proxy (§9), database + backups (§10), config reference (§11),
   systemd (§13).
2. → **[concepts.md](concepts.md)** — architecture, the two node types,
   capability naming, the self-care pattern, and the glossary.
3. → **[node/setup.md](node/setup.md)** — per node (repeat for each).
4. → **[reference/api.md](reference/api.md)** — full endpoint reference
   with cURL examples, payloads, and error codes.
5. → **[reference/design-board.md](reference/design-board.md)** — if you
   plan to run the message board (db-node + board-worker).

## 4. I want to use the API / write a client

→ **[reference/api.md](reference/api.md)** — every endpoint, auth
  requirements, cURL examples, and the common error codes.
→ **[concepts.md](concepts.md)** — credential families and lifecycle.

## 5. I want to understand the concepts

→ **[concepts.md](concepts.md)** — start here. Covers what the relay is,
  capabilities, tokens, node types, the self-care pattern, and a glossary.

## Quick decision tree

```
What do you want to do?
│
├─ Run a node (relay already exists)        → node/setup.md
│
├─ Set up the relay
│   ├─ Just me + one node                   → server/setup.md, then node/setup.md
│   └─ A real cluster                       → server/setup.md, concepts.md, node/setup.md, reference/api.md
│
├─ Use the HTTP API / write a client        → reference/api.md
│
└─ Understand the architecture              → concepts.md
```