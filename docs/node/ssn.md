# Server-Side Node (SSN) — Implementation

> **Status:** implemented (T-069 SSN daemon + T-075 Dynamic Routes + T-076 SSN Proxy)

## What is an SSN?

An **SSN** is a node that runs on the **same host as the relay server**. It is not a special node type — it is a normal node that heartbeats specific capabilities. The only difference is network: it communicates over localhost (`http://127.0.0.1:8788`) and needs no external ports.

```
┌── Relay Host ─────────────────────────────┐
│                                            │
│  ┌─────────────────────┐                    │
│  │  Relay Server       │  localhost:8788   │
│  │  (FastAPI)          │                    │
│  └────────┬────────────┘                    │
│           │                                │
│  ┌────────▼────────────┐                    │
│  │  SSN Node           │                    │
│  │  (node-cli daemon)  │                    │
│  │                     │                    │
│  │  Capabilities:      │                    │
│  │  • ssn.pages        │                    │
│  │  • ssn.proxy        │                    │
│  └─────────────────────┘                    │
│                                            │
│  ┌─────────────────────┐                    │
│  │  SSN Proxy           │  localhost:8790   │
│  │  (HTMX server)       │                    │
│  └─────────────────────┘                    │
└────────────────────────────────────────────┘
```

## Capabilities

### `ssn.pages`

Hosts HTML dashboard pages for other capabilities. External worker nodes (e.g. a Mac) deploy their dashboard pages by sending tasks to this capability.

**Flow:**
1. SSN heartbeats `ssn.pages` — the relay treats it like any other node
2. Worker uploads HTML via `node-cli artifact upload`
3. Worker sends task to `ssn.pages`: `{"action": "add", "capability": "image.generate.mflux", "artifact_id": "artifact_xxx"}`
4. SSN claims the task, downloads the artifact, stores it as `~/.ssn/pages/image.generate.mflux.html`
5. Dashboard shows the capability as clickable
6. Click → Relay proxies to SSN Proxy → SSN Proxy serves the HTML

**Actions:**

| Action | Payload | Description |
|--------|---------|-------------|
| **add** | `{"action": "add", "capability": "...", "artifact_id": "..."}` | SSN downloads artifact, stores as `<capability>.html` |
| **update** | `{"action": "update", "capability": "...", "artifact_id": "..."}` | SSN replaces existing HTML |
| **delete** | `{"action": "delete", "capability": "..."}` | SSN deletes the HTML file |
| **list** | `{"action": "list"}` | SSN responds with `{"capabilities": ["...", ...]}` |

### `ssn.proxy`

Provides API proxy endpoints for dashboard pages. This capability is **non-claimable** (`claimable: false`) — it only registers Dynamic Routes, never claims tasks.

The SSN Proxy runs an HTMX server on `localhost:8790` that:
- Serves HTML pages for capabilities (e.g. mflux form)
- Proxies API calls to the relay using the SSN node token
- Handles task submission, polling, and artifact download

**Architecture:**

```
Browser (Dashboard iFrame)
       │
       │ Session cookie
       ▼
Relay (192.168.2.60:8788)
       │
       │ Checks auth → forwards to Dynamic Route
       ▼
SSN Proxy (127.0.0.1:8790)
       │
       │ SSN node token
       ▼
Relay (127.0.0.1:8788)
```

**No session cookie for task-submit or storage.** The browser sends the session cookie only to the relay. The relay checks permissions and forwards internally to the SSN proxy. The SSN proxy injects its node token and makes the actual API call.

**Endpoints:**

| Path | Method | Description |
|------|--------|-------------|
| `/api/task-submit` | POST | Submit a task to the relay (with SSN node token) |
| `/api/tasks/{id}` | GET | Get task status from the relay |
| `/api/storage/{id}` | GET | Download an artifact from the relay |
| `/mflux` | GET | mflux capability page (HTMX) |
| `/mflux/generate` | POST | Generate an image (submit task → poll → result) |
| `/mflux/bilder/{id}` | GET | Serve a cached image |

**Dynamic Routes (registered in heartbeat):**

```yaml
capabilities:
  - name: ssn.proxy
    version: "1.0.0"
    auto_publish: true
    claimable: false
    description: "API proxy for capability pages."
    routes:
      - path: /api/task-submit
        method: POST
        auth: session
        upstream: http://127.0.0.1:8790/api/task-submit
      - path: /api/tasks/{id}
        method: GET
        auth: session
        upstream: http://127.0.0.1:8790/api/tasks/{id}
      - path: /api/storage/{id}
        method: GET
        auth: session
        upstream: http://127.0.0.1:8790/api/storage/{id}
      - path: /image.generate.mflux
        method: GET
        auth: session
        upstream: http://127.0.0.1:8790/mflux
```

Routes are reachable at:
```
/relay/v2/dashboard/api/node-routes/{node_id}/api/task-submit
/relay/v2/dashboard/api/node-routes/{node_id}/api/tasks/{id}
/relay/v2/dashboard/api/node-routes/{node_id}/api/storage/{id}
```

## HTMX capability pages

Capability pages are **pure HTML templates with HTMX** — no client-side JavaScript. HTMX makes AJAX requests from HTML attributes. The server returns HTML snippets.

**Benefits:**
- No client-side `fetch()` — no CSRF issues
- No session cookie for API calls
- Images embedded as Base64 data URLs (no separate image request)
- Simple forms instead of async JS spaghetti

**Important: Node-ID-agnostic paths**

The HTML page must **not** hardcode absolute paths or the node_id. Since the Dynamic Route carries the node_id in the path (`/api/node-routes/{node_id}/mflux`), all HTMX requests must be **relative**.

**Correct (relative):**
```html
<form hx-post="mflux/generate" hx-target="#result">
```

**Wrong (absolute):**
```html
<form hx-post="/mflux/generate" hx-target="#result">
```

Images are embedded as Base64 data URLs directly in the HTML:
```python
import base64
img_b64 = base64.b64encode(img_data).decode()
html = f'<img src="data:image/png;base64,{img_b64}" alt="Image">'
```

## Deployment

### 1. SSN daemon

The SSN daemon runs as a systemd user unit:

```bash
cp systemd/ai-relay-ssn.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now ai-relay-ssn.service
```

### 2. SSN Proxy

```bash
cp systemd/ai-relay-ssn-proxy.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now ai-relay-ssn-proxy.service
```

### 3. Capability profile

```yaml
# ~/.relay/profiles.d/ssn.yaml
capabilities:
  - name: ssn.pages
    version: "1.0.0"
    type: native
    description: "Hosts HTML dashboard pages for other capabilities."
    auto_publish: true
    claimable: true
    handler: /home/felix/projects/ai-relay-service/nodes/handlers/ssn-capability-pages.sh
    max_parallel: 1
    timeout: 300

  - name: ssn.proxy
    version: "1.0.0"
    auto_publish: true
    claimable: false
    description: "API proxy for capability pages."
    routes:
      - path: /api/task-submit
        method: POST
        auth: session
        upstream: http://127.0.0.1:8790/api/task-submit
      - path: /api/tasks/{id}
        method: GET
        auth: session
        upstream: http://127.0.0.1:8790/api/tasks/{id}
      - path: /api/storage/{id}
        method: GET
        auth: session
        upstream: http://127.0.0.1:8790/api/storage/{id}
```

Publish:
```bash
node-cli capabilities publish ssn
```

## See also

- **[concept.md](concept.md)** — what a node is
- **[capability-concept.md](capability-concept.md)** — what a capability is
- **[capabilities.md](capabilities.md)** — capability reference, naming, handler contract, Dynamic Routes
- **[node-config.md](node-config.md)** — `node.yaml` format
- **[federation.md](federation.md)** — Federation Node implementation
