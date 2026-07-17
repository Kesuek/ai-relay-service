# API Reference

All endpoints are served under the `/relay/v2` prefix (the v2 router), except
`/health` which is served at the root. Most node-facing endpoints require a
`rt_...` runtime token in the `Authorization: Bearer` header. Dashboard API
endpoints require a signed session cookie.

For the concepts behind these endpoints see [../concepts.md](../concepts.md).
For node-side usage see [../node/setup.md](../node/setup.md).

## Health

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | none | Liveness check |

## Auth — `/relay/v2/auth`

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/relay/v2/auth/register` | none | Register a worker/service node → returns `node_id`, temporary token, registration secret |
| POST | `/relay/v2/auth/register-admin` | `adm_...` bootstrap secret | Register an admin node directly with a runtime token |
| POST | `/relay/v2/auth/refresh` | `rt_...` or `rs_...` | Rotate the runtime token or the registration secret |
| POST | `/relay/v2/auth/status` | `rt_...` or `rs_...` (read-only) | Report credential lifetimes; pending nodes may poll unauthenticated with the registration secret |

## Discovery — `/relay/v2/discovery`

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/relay/v2/discovery/heartbeat` | `rt_...` | Send heartbeat with capabilities, load, queue_depth |
| POST | `/relay/v2/discovery/worker-heartbeat` | `rt_...` | Worker heartbeat variant — accepts full capability dicts and **replaces** the node's advertised capabilities (`replace_capabilities=True`). Same payload fields as `/heartbeat` (`load`, `queue_depth`, `available`, `endpoint`, `capabilities`), but `capabilities` is an open `List[dict]` of full capability objects rather than status records. Use this when a worker publishes its complete, authoritative capability set on every heartbeat. |
| GET | `/relay/v2/discovery/nodes` | `rt_...` | List nodes known to the relay |
| GET | `/relay/v2/discovery/query` | `rt_...` | Query the capability registry |
| GET | `/relay/v2/discovery/capabilities` | `rt_...` | List all advertised capabilities |
| GET | `/relay/v2/discovery/capabilities/{name}` | `rt_...` | Detail for a single capability |

## Scheduler — `/relay/v2/scheduler`

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/relay/v2/scheduler/tasks` | `rt_...` | Submit a task DAG |
| GET | `/relay/v2/scheduler/tasks` | `rt_...` | List tasks |
| GET | `/relay/v2/scheduler/tasks/{task_id}` | `rt_...` | Task detail |
| POST | `/relay/v2/scheduler/task-simple` | `rt_...` | Submit a single-stage task (simplified) |
| POST | `/relay/v2/scheduler/claim` | `rt_...` | Claim one pending stage for a capability |
| POST | `/relay/v2/scheduler/stages/{stage_id}/complete` | `rt_...` | Complete a claimed stage with a result dict |
| POST | `/relay/v2/scheduler/enforce-timeouts` | `rt_...` (admin) | Enforce stage timeouts |
| POST | `/relay/v2/scheduler/artifacts/{task_id}` | `rt_...` | Associate artifacts with a task |
| GET | `/relay/v2/scheduler/artifacts/{task_id}` | `rt_...` | List artifacts for a task |
| DELETE | `/relay/v2/scheduler/artifacts/{artifact_id}` | `rt_...` | Remove an artifact association |

## Presence — `/relay/v2/presence`

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/relay/v2/presence/update` | `rt_...` | Update presence state (informational) |
| GET | `/relay/v2/presence/nodes` | `rt_...` | List presence records |
| GET | `/relay/v2/presence/{node_id}` | `rt_...` | Presence record for a node |

## Events — `/relay/v2/events`

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/relay/v2/events/stream` | `rt_...` (`?node=<id>`) | Real-time SSE event stream |

## Storage — `/relay/v2/storage`

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/relay/v2/storage/upload` | `rt_...` | Upload a file as an artifact (multipart, default limit 100 MiB) |
| GET | `/relay/v2/storage/files/{artifact_id}` | `rt_...` | Download an artifact (streams in 64 KiB chunks) |
| GET | `/relay/v2/storage/files/{artifact_id}/meta` | `rt_...` | Artifact metadata |
| DELETE | `/relay/v2/storage/files/{artifact_id}` | `rt_...` | Delete an artifact |
| GET | `/relay/v2/storage/list` | `rt_...` | List artifacts (`?task_id=…`) |
| POST | `/relay/v2/storage/chunked/init` | `rt_...` | Start a chunked upload |
| POST | `/relay/v2/storage/chunked/{upload_id}/chunk` | `rt_...` | Upload one chunk |
| POST | `/relay/v2/storage/chunked/{upload_id}/complete` | `rt_...` | Finalise a chunked upload |

## Dashboard — `/relay/v2/dashboard`

Pages and JSON API used by the dashboard UI. Session-cookie auth unless noted.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/relay/v2/dashboard/` | session | Dashboard home |
| GET | `/relay/v2/dashboard/login` | none | Login page |
| POST | `/relay/v2/dashboard/login` | none | Authenticate, set session cookie |
| GET | `/relay/v2/dashboard/bootstrap` | none | First-admin creation page (master seed) |
| POST | `/relay/v2/dashboard/api/bootstrap` | master seed | Create the first human admin |
| POST | `/relay/v2/dashboard/logout` | session | Clear session |
| GET | `/relay/v2/dashboard/change-password` | session | Forced password-change page |
| GET | `/relay/v2/dashboard/api/me` | session | Current user info |
| POST | `/relay/v2/dashboard/api/me/password` | session | Change own password |
| GET | `/relay/v2/dashboard/api/overview` | session | Cluster overview JSON |
| GET | `/relay/v2/dashboard/api/endpoints` | session | List dashboard API endpoints |
| GET | `/relay/v2/dashboard/api/events/recent` | session | Recent events for the overview |
| GET | `/relay/v2/dashboard/api/users` | session | List users |
| POST | `/relay/v2/dashboard/api/users` | session | Create user |
| POST | `/relay/v2/dashboard/api/users/{user_id}/groups` | session | Set user groups |
| POST | `/relay/v2/dashboard/api/users/{user_id}/password` | session | Reset password |
| POST | `/relay/v2/dashboard/api/users/{user_id}/active` | session | Activate/deactivate |
| DELETE | `/relay/v2/dashboard/api/users/{user_id}` | session | Delete user |
| GET | `/relay/v2/dashboard/api/groups` | session | List groups |
| GET | `/relay/v2/dashboard/api/permissions` | session | List permissions |
| POST | `/relay/v2/dashboard/api/groups/{group_id}/permissions` | session | Set group permissions |
| GET | `/relay/v2/dashboard/static/{filename}` | none | Static dashboard assets |

## Admin — `/relay/v2/admin`

Requires an admin runtime token.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/relay/v2/admin/nodes` | `rt_...` (admin) | List all nodes |
| POST | `/relay/v2/admin/nodes/{node_id}/approve` | `rt_...` (admin) | Approve a pending node → issues runtime token |
| POST | `/relay/v2/admin/nodes/{node_id}/token` | `rt_...` (admin) | Issue a new runtime token (invalidates previous) |
| DELETE | `/relay/v2/admin/nodes/{node_id}` | `rt_...` (admin) | Delete a node and its records |

## Docs — `/relay/v2/docs`

Serves selected Markdown documents as HTML. The whitelist is defined in
`src/relay_server/api/v2/docs.py`.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/relay/v2/docs` | none | JSON index of public documents |
| GET | `/relay/v2/docs/{doc_name}` | none | Render a public Markdown document as HTML |

## Worked examples (cURL)

The examples below use the shell variable `RELAY_HOST` (e.g.
`export RELAY_HOST=ai-relay.local`) and assume the default port `8788`. JSON
output is piped through `jq` for readability; install it or drop the pipe.
Replace the placeholder tokens (`rt_…`, `rs_…`, `adm_…`) with your own.

### Common error responses

Every endpoint returns a JSON error object on failure. The most common
status codes are:

| Status | Meaning | Typical cause |
|---|---|---|
| `400` | Bad request | Malformed JSON, missing required field, payload too large |
| `401` | Unauthorized | Missing/invalid/expired `Authorization: Bearer` token |
| `403` | Forbidden | Token valid but not allowed (e.g. pending node, non-admin) |
| `404` | Not found | Unknown `node_id` / `task_id` / `stage_id` / `artifact_id` |
| `409` | Conflict | Duplicate `node_name` or `node_id` already exists |
| `422` | Validation error | Pydantic validation failed (field-level errors in `detail`) |
| `429` | Too many requests | Rate limit hit (see per-endpoint limits below) |
| `413` | Payload too large | Upload exceeds `max_upload_bytes` (default 100 MiB) |
| `500` | Internal server error | Relay bug — check the server log |

Rate limits: `register` 10/min, `register-admin` 5/min, `refresh`/`status`
30/min. All other node-facing endpoints are currently unlimited.

Error body shape (FastAPI default):

```json
{ "detail": "Invalid or expired runtime token" }
```

### Register a worker node

```bash
curl -s -X POST "http://${RELAY_HOST}:8788/relay/v2/auth/register" \
  -H "Content-Type: application/json" \
  -d '{
    "node_name": "my-node",
    "endpoint": null,
    "role": "service",
    "capabilities": [{"name": "storage.archive.native", "version": "1.0.0"}]
  }' | jq
```

```json
{
  "node_id": "V34ETT74",
  "node_name": "my-node",
  "status": "pending",
  "token_type": "temporary",
  "token": "tp_...",
  "expires_at": "2026-07-18T10:23:11+00:00",
  "registration_secret": "rs_..."
}
```

Errors: `409` if `node_name` already exists; `422` if `capabilities` is
malformed.

### Register an admin node (master seed)

```bash
curl -s -X POST "http://${RELAY_HOST}:8788/relay/v2/auth/register-admin" \
  -H "Content-Type: application/json" \
  -d '{
    "node_name": "admin-cli",
    "bootstrap_secret": "adm_...",
    "endpoint": null,
    "capabilities": [{"name": "admin", "version": "1.0.0"}]
  }' | jq
```

```json
{
  "node_id": "AB12CD34",
  "node_name": "admin-cli",
  "status": "approved",
  "token_type": "runtime",
  "token": "rt_...",
  "expires_at": "2026-07-24T10:23:11+00:00"
}
```

Errors: `401` if the bootstrap secret is wrong or the master seed has not
been initialised on the relay host.

### Heartbeat

```bash
curl -s -X POST "http://${RELAY_HOST}:8788/relay/v2/discovery/heartbeat" \
  -H "Authorization: Bearer rt_..." \
  -H "Content-Type: application/json" \
  -d '{
    "available": true,
    "load": 0.0,
    "queue_depth": 0,
    "capabilities": [{"name": "storage.archive.native", "version": "1.0.0"}]
  }' | jq
```

Response (200):

```json
{
  "node_id": "V34ETT74",
  "status": "ok",
  "previous_status": "approved",
  "last_seen": "2026-07-17T10:23:11+00:00"
}
```

Errors: `401` token invalid/expired; `403` node not approved yet (poll
`/auth/status`).

### Claim a stage

```bash
curl -s -X POST "http://${RELAY_HOST}:8788/relay/v2/scheduler/claim" \
  -H "Authorization: Bearer rt_..." \
  -H "Content-Type: application/json" \
  -d '{"capability": "storage.archive.native"}' | jq
```

```json
{
  "claimed": true,
  "stage": {
    "stage_id": "stg_abc123",
    "task_id": "tsk_def456",
    "stage_name": "archive",
    "capability": "storage.archive.native",
    "status": "claimed",
    "depends_on": null,
    "claimed_by": "V34ETT74",
    "claimed_at": "2026-07-17T10:23:12+00:00",
    "completed_at": null,
    "payload": { "file_name": "report.pdf", "target_path": "/nas/archive" },
    "result": null
  }
}
```

If no pending stage matches: `{"claimed": false, "stage": null}` (still
`200`). Errors: `401` token; `403` capability not advertised in the latest
heartbeat.

### Complete a stage

```bash
curl -s -X POST \
  "http://${RELAY_HOST}:8788/relay/v2/scheduler/stages/stg_abc123/complete" \
  -H "Authorization: Bearer rt_..." \
  -H "Content-Type: application/json" \
  -d '{
    "result": {"status": "archived", "bytes": 1234567},
    "artifacts": ["artifact_xYz"]
  }' | jq
```

```json
{ "ok": true, "stage_id": "stg_abc123", "status": "completed" }
```

To report a failure, put the error inside the result dict instead of
raising — the relay stores it on the stage:

```bash
curl -s -X POST \
  "http://${RELAY_HOST}:8788/relay/v2/scheduler/stages/stg_abc123/complete" \
  -H "Authorization: Bearer rt_..." \
  -H "Content-Type: application/json" \
  -d '{"result": {"error": "disk full on /nas/archive"}}' | jq
```

Errors: `404` unknown stage; `409` stage not claimed by this node or already
completed.

### Submit a task

Full DAG form (`POST /relay/v2/scheduler/tasks`):

```bash
curl -s -X POST "http://${RELAY_HOST}:8788/relay/v2/scheduler/tasks" \
  -H "Authorization: Bearer rt_..." \
  -H "Content-Type: application/json" \
  -d '{
    "task_name": "archive-and-notify",
    "priority": 3,
    "stages": [
      {
        "stage_name": "archive",
        "capability": "storage.archive.native",
        "payload": {"file_name": "report.pdf", "target_path": "/nas/archive"}
      },
      {
        "stage_name": "notify",
        "capability": "chat.ai",
        "depends_on": ["archive"],
        "payload": {"message": "Archive completed"}
      }
    ]
  }' | jq
```

```json
{
  "task_id": "tsk_def456",
  "task_name": "archive-and-notify",
  "status": "pending",
  "stages": [
    { "stage_id": "stg_abc123", "stage_name": "archive", "status": "pending" },
    { "stage_id": "stg_ghi789", "stage_name": "notify",  "status": "pending" }
  ]
}
```

Simplified single-stage form (`POST /relay/v2/scheduler/task-simple`):

```bash
curl -s -X POST "http://${RELAY_HOST}:8788/relay/v2/scheduler/task-simple" \
  -H "Authorization: Bearer rt_..." \
  -H "Content-Type: application/json" \
  -d '{
    "capability": "chat.ai",
    "payload": {"question": "What is the time in Tokyo?"},
    "name": "tokyo-time",
    "priority": 3
  }' | jq
```

```json
{
  "task_id": "tsk_qrs012",
  "stage_id": "stg_tuv345",
  "status": "pending",
  "capability": "chat.ai"
}
```

Errors: `422` validation (payload > `max_payload_bytes`, priority out of
`0..10`); `404` if a `depends_on` stage id does not exist within the task.

### Upload an artifact

Multipart upload (default limit 100 MiB):

```bash
curl -s -X POST "http://${RELAY_HOST}:8788/relay/v2/storage/upload" \
  -H "Authorization: Bearer rt_..." \
  -F "file=@/tmp/report.pdf" \
  -F "task_id=tsk_def456" \
  -F "stage_id=stg_abc123" | jq
```

```json
{
  "artifact_id": "artifact_a1B2c3D4",
  "name": "report.pdf",
  "path": "/home/felix/.relay/artifacts/artifact_a1B2c3D4",
  "size_bytes": 1234567,
  "mime_type": "application/pdf",
  "created_by": "V34ETT74"
}
```

Errors: `413` file larger than `max_upload_bytes`; `422` missing `file`
field.

For files larger than 100 MiB use the **chunked** upload flow:
`POST /relay/v2/storage/chunked/init` →
`POST /relay/v2/storage/chunked/{upload_id}/chunk` (repeated, base64 data) →
`POST /relay/v2/storage/chunked/{upload_id}/complete`.

### Download an artifact

```bash
curl -s -X GET "http://${RELAY_HOST}:8788/relay/v2/storage/files/artifact_a1B2c3D4" \
  -H "Authorization: Bearer rt_..." \
  -o /tmp/report.pdf
```

The relay streams the file in 64 KiB chunks. Metadata only:

```bash
curl -s "http://${RELAY_HOST}:8788/relay/v2/storage/files/artifact_a1B2c3D4/meta" \
  -H "Authorization: Bearer rt_..." | jq
```

### Refresh / recover a token

Rotate the runtime token (old one invalidated immediately):

```bash
curl -s -X POST "http://${RELAY_HOST}:8788/relay/v2/auth/refresh" \
  -H "Authorization: Bearer rt_..." \
  -H "Content-Type: application/json" \
  -d '{"requested_credential": "runtime_token"}' | jq
```

Recover a lost runtime token with the registration secret (no Bearer
header; rotates the registration secret too):

```bash
curl -s -X POST "http://${RELAY_HOST}:8788/relay/v2/auth/refresh" \
  -H "Content-Type: application/json" \
  -d '{
    "node_id": "V34ETT74",
    "registration_secret": "rs_...",
    "requested_credential": "runtime_token"
  }' | jq
```

```json
{
  "node_id": "V34ETT74",
  "node_name": "my-node",
  "token_type": "runtime",
  "token": "rt_new...",
  "expires_at": "2026-07-24T10:23:11+00:00",
  "message": "Runtime token recovered; registration secret rotated"
}
```

Errors: `401` registration secret invalid/expired; `403` node not approved;
`404` unknown `node_id`. See [../node/token-lifecycle.md](../node/token-lifecycle.md)
for the full flow.

## Next steps

- [../concepts.md](../concepts.md) — architecture and credential concepts
- [../node/setup.md](../node/setup.md) — node setup walkthrough
- [../server/admin.md](../server/admin.md) — admin operations
- [design-board.md](design-board.md) — message board design