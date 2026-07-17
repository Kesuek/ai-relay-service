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
| POST | `/relay/v2/discovery/worker-heartbeat` | `rt_...` | Worker heartbeat variant (writes `worker_status`) |
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

## Next steps

- [../concepts.md](../concepts.md) — architecture and credential concepts
- [../node/setup.md](../node/setup.md) — node setup walkthrough
- [../server/admin.md](../server/admin.md) — admin operations
- [design-board.md](design-board.md) — message board design