# Server-Side Node (SSN)

> **Status: implemented with T-069 (SSN daemon) + T-075 (Dynamic Routes) + T-076 (SSN Proxy).**

## What is an SSN?

A **Server-Side Node (SSN)** is a normal `node-cli` daemon that runs on the
**same host as the relay server**. It heartbeats capabilities, claims tasks and
completes them — just like any other worker node. The difference: it needs no
external network port because it communicates over localhost
(`http://127.0.0.1:8788`).

SSNs fill the gap between the relay core and external worker nodes. They host
services that need low latency, access to relay-internal APIs, or the ability to
orchestrate other nodes without exposing a public endpoint.

## Capability: `ssn.capability-pages`

The reference SSN heartbeats the `ssn.capability-pages` capability and signals:
"I can host HTML dashboard pages for other capabilities." External worker nodes
(e.g. a Mac) manage their HTML pages by sending tasks to this capability — the
SSN runs the handler and caches the HTML locally under
`~/.ssn/pages/<capability>.html`.

### Flow

1. **SSN heartbeats** `ssn.capability-pages` — the relay treats it like any
   other node.
2. **Worker wants to deploy a dashboard page**: Worker uploads the HTML via
   `node-cli artifact upload`, then sends a task to `ssn.capability-pages` with
   `{"action":"add","capability":"image.generate.mflux","artifact_id":"artifact_xxx"}`.
3. **SSN claims the task**, runs `ssn-capability-pages.sh`, downloads the
   artifact via `node-cli artifact download` and stores it as
   `~/.ssn/pages/image.generate.mflux.html`.
4. **Dashboard** shows in the **Capabilities** list that an SSN node offers
   `ssn.capability-pages`.

### HTML management via tasks

| Action | Task payload | Description |
|--------|-------------|-------------|
| **add** | `{"action": "add", "capability": "image.generate.mflux", "artifact_id": "artifact_xxx"}` | SSN downloads the artifact and stores it as `<capability>.html` |
| **update** | `{"action": "update", "capability": "image.generate.mflux", "artifact_id": "artifact_yyy"}` | SSN replaces the existing HTML with the new one |
| **delete** | `{"action": "delete", "capability": "image.generate.mflux"}` | SSN deletes the HTML file |
| **list** | `{"action": "list"}` | SSN responds with `{"capabilities": ["image.generate.mflux", …]}` |

## SSN Proxy (T-076)

Since T-076, an **SSN Proxy** runs on the SSN host — an HTMX server on
`127.0.0.1:8790`. It heartbeats its endpoints as **Dynamic Routes** (T-075)
and handles all relay interactions server-side using the SSN node token.

### Architecture

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

**No session cookie for task-submit or storage.** The browser sends the session
cookie only to the relay. The relay checks permissions and forwards internally
to the SSN proxy. The SSN proxy injects its node token and makes the actual
API call.

### Endpoints

| Path | Method | Description |
|------|--------|-------------|
| `/api/task-submit` | POST | Submit a task to the relay (with SSN node token) |
| `/api/tasks/{id}` | GET | Get task status from the relay |
| `/api/storage/{id}` | GET | Download an artifact from the relay |
| `/mflux` | GET | mflux capability page (HTMX) |
| `/mflux/generate` | POST | Generate an image (submit task → poll → result) |
| `/mflux/bilder/{id}` | GET | Serve a cached image |

### Dynamic Routes

The SSN proxy heartbeats its API endpoints as Dynamic Routes under the
`ssn.proxy` capability (not claimable — it only provides routes, not
task handlers):

```yaml
capabilities:
  - name: ssn.capability-pages
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
      - path: /image.generate.mflux
        method: GET
        auth: session
        upstream: http://127.0.0.1:8790/mflux
```

The routes are reachable at:
```
/relay/v2/dashboard/api/node-routes/{node_id}/api/task-submit
/relay/v2/dashboard/api/node-routes/{node_id}/api/tasks/{id}
/relay/v2/dashboard/api/node-routes/{node_id}/api/storage/{id}
```

### Capability Pages with HTMX

Capability pages are **pure HTML templates with HTMX** — no client-side
JavaScript. HTMX is a ~14KB JS library that makes AJAX requests from HTML
attributes. The server returns HTML snippets.

**Benefits:**
- No client-side `fetch()` — no CSRF issues
- No session cookie for API calls
- Images are embedded as Base64 data URLs (no separate image request)
- Simple forms instead of async JS spaghetti

**Important: Node-ID-agnostic paths**

The HTML page must **not** hardcode absolute paths or the node_id. Since the
Dynamic Route carries the node_id in the path
(`/api/node-routes/{node_id}/mflux`), all HTMX requests must be **relative**.
Otherwise links break if the SSN gets a new node_id (e.g. after re-registration).

**Correct (relative):**
```html
<form hx-post="mflux/generate" hx-target="#result">
```

**Wrong (absolute):**
```html
<form hx-post="/mflux/generate" hx-target="#result">
```

Images are embedded as Base64 data URLs directly in the HTML, instead of
loading them via a separate image endpoint. This avoids an extra round-trip
through the Dynamic Route and makes the page independent of the node_id:

```python
import base64
img_b64 = base64.b64encode(img_data).decode()
html = f'<img src="data:image/png;base64,{img_b64}" alt="Image">'
```

**Example (mflux page):**
```html
<form hx-post="mflux/generate" hx-target="#result">
  <textarea name="prompt" required></textarea>
  <select name="format">
    <option value="quadrat">Square (512×512)</option>
  </select>
  <button type="submit">✨ Generate</button>
</form>
<div id="result"></div>
```

## Deployment

### 1. SSN daemon (T-069)

See [setup.md](../server/setup.md) for server config (`ssn_enabled`,
`ssn_auto_approve`). The SSN daemon runs as a systemd user unit:

```bash
cp systemd/ai-relay-ssn.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now ai-relay-ssn.service
```

### 2. SSN Proxy (T-076)

```bash
cp systemd/ai-relay-ssn-proxy.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now ai-relay-ssn-proxy.service
```

### 3. Capability profile

```yaml
# ~/.relay/profiles.d/ssn.yaml
capabilities:
  - name: ssn.capability-pages
    version: "1.0.0"
    type: native
    description: "Server-Side Node — hosts HTML dashboard pages"
    auto_publish: true
    claimable: true
    handler: /home/felix/projects/ai-relay-service/nodes/handlers/ssn-capability-pages.sh
    max_parallel: 1
    timeout: 300
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

- [Capabilities](capabilities.md) — capability names, suffixes, handler contract, Dynamic Routes
- [node-cli reference](cli-reference.md) — `task submit`, `artifact upload`, `artifact download`
- [Server setup](../server/setup.md) — `ssn_enabled`/`ssn_auto_approve` config
