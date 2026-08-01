# Capability Concept

## What is a Capability?

A **capability** is a named, typed, versioned thing a node can do. It is the routing key for tasks — the relay matches incoming tasks to nodes by capability name.

```
Task: { capability: "image.generate.mflux", payload: { prompt: "fox" } }
         │
         ▼
Relay: "Which node heartbeats image.generate.mflux?"
         │
         ▼
Node: "I do. I claim this task."
```

A capability is **not** a tool, a model, or a service. It is a **label** that a node advertises. What happens when the node claims a task for that capability is entirely up to the node.

## What every capability has

| Field | Required | Description |
|-------|----------|-------------|
| **name** | ✅ | Dot-separated namespace, e.g. `chat.ai`, `image.generate.mflux` |
| **type** | ✅ | How the node executes: `native` (built-in), `shell` (script), `http` (API call), `ai` (Hermes agent) |
| **claimable** | ✅ | Whether the scheduler assigns tasks for this capability (`true`) or it only provides routes/pages (`false`) |
| **handler** | * | Path to the script or command that executes the task (required for `claimable: true`) |
| **version** | — | Semver string, e.g. `1.0.0` |
| **description** | — | Human-readable explanation of what this capability does |
| **input_schema** | — | JSON Schema describing the expected task payload |
| **max_parallel** | — | How many tasks this node can execute concurrently for this capability |
| **timeout** | — | Max seconds a task may run before being marked as timed out |

## What a capability does

### 1. It is advertised by a node

A node includes its capabilities in every heartbeat. The relay stores the most recent set. A node can change its capabilities at any time — the next heartbeat updates them.

```json
// Heartbeat payload
{
  "capabilities": [
    { "name": "chat.ai", "version": "1.0.0", "type": "ai" },
    { "name": "image.generate.mflux", "version": "2.0.0", "type": "native" }
  ]
}
```

### 2. It routes tasks

When a task is submitted with a capability name, the relay finds all nodes that heartbeat that capability and assigns the task to one of them (via the claim mechanism).

```
Task: capability = "chat.ai"
         │
         ▼
Relay: "3 nodes heartbeat chat.ai. Pick the one with lowest load."
         │
         ▼
Node X claims the task → executes → completes
```

### 3. It can have a dashboard page

A capability can provide an HTML dashboard page. When a user clicks on the capability in the dashboard, the page is shown. This allows capabilities to have their own UI — e.g. an image generator with a prompt form, or a federation manager with checkboxes.

Pages are hosted by the **SSN** (via `ssn.pages` capability) or by the node itself via **Dynamic Routes**.

### 4. It can have dynamic routes

A capability can register HTTP endpoints that are proxied through the relay. This allows nodes to provide live, interactive APIs without opening ports. Routes are registered in the heartbeat and deregistered when the node goes offline.

```yaml
capabilities:
  - name: ssn.proxy
    claimable: false
    routes:
      - path: /api/task-submit
        method: POST
        auth: session
        upstream: http://127.0.0.1:8790/api/task-submit
```

### 5. It can be non-claimable

Not every capability needs to execute tasks. Some capabilities only exist to provide routes or pages:

- `ssn.proxy` — provides API proxy endpoints, never claims tasks
- `federation` — bridges remote relays, claims tasks for subscribed capabilities

A non-claimable capability is still advertised in the heartbeat — it just never appears in the claim queue.

## Capability vs Node

A **node** is the process. A **capability** is what the node can do.

```
Node A (Mac mini)
  ├── chat.ai              → LLM chat
  ├── image.generate.mflux → FLUX image generation
  └── image.upscale        → ESRGAN upscaling

Node B (Relay host)
  ├── ssn.pages            → Host dashboard pages
  └── ssn.proxy            → API proxy for pages

Node C (Federation bridge)
  └── federation           → Bridge to remote relay
```

One node, many capabilities. One capability, many nodes (for load balancing and failover).

## Capability lifecycle

```
[Defined in node.yaml] → [Published via heartbeat] → [Claimed by node] → [Task executed]
                              │
                              ├── [Dashboard page deployed] → [Visible in dashboard]
                              ├── [Dynamic routes registered] → [API accessible]
                              └── [Removed from heartbeat] → [No longer available]
```

## What a capability is NOT

- **Not a tool** — a capability is a routing label, not an executable
- **Not a model** — `chat.ai` does not specify which LLM runs behind it
- **Not a node** — a node heartbeats capabilities, it is not one itself
- **Not a service** — a capability does not run, a node runs
- **Not tied to a machine** — the same capability can run on many nodes

## Examples

### Skeleton `node.yaml`

```yaml
# ~/.relay/node.yaml
node_name: my-worker
description: "A multi-purpose worker node"

capabilities:
  - name: storage.archive
    type: shell
    claimable: true
    handler: /opt/relay/handlers/archive.sh
    max_parallel: 2
    timeout: 600
    description: "Compresses and archives files"

  - name: weather.current
    type: shell
    claimable: true
    handler: /opt/relay/handlers/weather.sh
    max_parallel: 5
    timeout: 30
    description: "Fetches current weather from OpenWeatherMap"
    input_schema:
      type: object
      properties:
        city:
          type: string
          description: "City name"
        units:
          type: string
          enum: [metric, imperial]
          default: metric

  - name: chat.ai
    type: ai
    claimable: true
    handler: /opt/relay/handlers/ollama-chat.sh
    max_parallel: 1
    timeout: 300
    description: "Chat with local Ollama LLM"
    input_schema:
      type: object
      properties:
        prompt:
          type: string
          description: "The user message"
        model:
          type: string
          default: llama3.2
          description: "Ollama model name"
```

### Example 1: Script capability — file archiver

**Capability:** `storage.archive`

**Handler script** (`/opt/relay/handlers/archive.sh`):
```bash
#!/usr/bin/env bash
# Reads task payload from stdin, archives the given path
eval "$(cat)"
tar -czf "/tmp/archive-$(date +%s).tar.gz" "$path"
echo "{\"archive_path\": \"/tmp/archive-...\"}"
```

**Task submission:**
```bash
node-cli task submit --capability storage.archive \
  --payload '{"path": "/home/user/documents"}'
```

**What happens:**
1. Node claims the task
2. Relay writes the payload to the handler's stdin
3. Handler runs `tar`, outputs result JSON to stdout
4. Node reads stdout, completes the stage with the result

### Example 2: Script → API capability — weather fetcher

**Capability:** `weather.current`

**Handler script** (`/opt/relay/handlers/weather.sh`):
```bash
#!/usr/bin/env bash
# Reads task payload, calls OpenWeatherMap API, returns result
eval "$(cat)"
API_KEY="${OPENWEATHER_API_KEY}"
UNITS="${units:-metric}"
URL="https://api.openweathermap.org/data/2.5/weather?q=${city}&units=${UNITS}&appid=${API_KEY}"
curl -s "$URL"
```

**Task submission:**
```bash
node-cli task submit --capability weather.current \
  --payload '{"city": "Leipzig", "units": "metric"}'
```

**What happens:**
1. Node claims the task
2. Handler receives `{"city": "Leipzig", "units": "metric"}`
3. Handler calls OpenWeatherMap API via `curl`
4. API response is written to stdout
5. Node reads stdout, completes the stage with the API result

### Example 3: AI capability — Ollama chat

**Capability:** `chat.ai`

**Handler script** (`/opt/relay/handlers/ollama-chat.sh`):
```bash
#!/usr/bin/env bash
# Reads task payload, calls local Ollama, returns response
eval "$(cat)"
MODEL="${model:-llama3.2}"
RESPONSE=$(curl -s http://localhost:11434/api/generate \
  -d "{\"model\": \"$MODEL\", \"prompt\": \"$prompt\", \"stream\": false}")
echo "$RESPONSE"
```

**Task submission:**
```bash
node-cli task submit --capability chat.ai \
  --payload '{"prompt": "What is the capital of France?", "model": "llama3.2"}'
```

**What happens:**
1. Node claims the task
2. Handler receives `{"prompt": "What is the capital of France?", "model": "llama3.2"}`
3. Handler calls local Ollama API (`localhost:11434`)
4. Ollama generates the response
5. Handler outputs the response JSON to stdout
6. Node completes the stage with the LLM response

### Summary

| Type | Handler does | Example |
|------|-------------|---------|
| **Script** (`type: shell`) | Runs a local script or binary | `storage.archive` — runs `tar` |
| **Script → API** (`type: shell`) | Calls an external HTTP API | `weather.current` — calls OpenWeatherMap |
| **AI** (`type: ai`) | Calls a local or remote LLM | `chat.ai` — calls Ollama |

The handler contract is always the same:
1. Task payload arrives on **stdin** as JSON
2. Handler processes it (runs a command, calls an API, invokes an LLM)
3. Handler writes the result to **stdout** as JSON
4. Node reads stdout and completes the stage

## See also

- **[capabilities.md](capabilities.md)** — detailed reference: naming & suffixes, `chat.ai` vs `agent.ai`, `node.yaml` format, Dynamic Routes, handler contract, validation rules, metadata forwarding
- **[node-config.md](node-config.md)** — `node.yaml` reference with all fields
- **[ssn.md](ssn.md)** — SSN capability pages and proxy
- **[concept.md](concept.md)** — what a node is
