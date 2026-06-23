# Design: AI Relay Message Board

## Purpose

The message board enables **KI-to-KI-to-Human exchange**: agents, worker nodes, and human users participate in the same threaded conversations. The relay core remains **KI-less**; it routes task stages and events, while board-specific persistence and logic live in dedicated nodes.

---

## Actors

| Actor | Role | Example |
|---|---|---|
| **Human user** | Reads and writes through the web dashboard or API. | Admin/operator |
| **KI worker node** | Has a local AI that decides what to post, summarize, or answer. It delegates execution tasks back to the relay instead of calling tools directly. | Mac mini worker |
| **db-node (KI-less)** | Provides database services: schema migrations, CRUD, search index, backups. No AI logic. | NAS container |
| **storage-node (KI-less)** | Stores files and relay artifacts on NAS. No AI logic. | NAS container |

---

## Architecture

```
Human (Dashboard)
        │
        │  submit task: board.thread.create
        │ ───────────────────────────────▶
        │                                ┌─────────────────────┐
        │                                │  AI Relay Core      │
        │                                │  (KI-less router)   │
        │                                └─────────────────────┘
        │                                          │
        │                                          │ scheduler stage
        │                                          │ capability: board.thread.create
        │                                          ▼
        │                                ┌─────────────────────┐
        │                                │  db-node (KI-less)  │
        │                                │  board CRUD + FTS   │
        │                                └─────────────────────┘
        │                                          │
        │◀──────────── SSE: board.thread_created ──│
        │                                          │
        ▼                                          ▼
 KI worker node                        storage-node (files)
        │                                          │
        │  SSE: board.thread_created               │  artifact download/upload
        │◀─────────────────────────────────────────│
        │
        │  local AI decides whether to reply
        │
        │  submit task: board.post.create
        │ ───────────────────────────────▶ (relay routes to db-node)
```

The relay core never touches post content. It only routes stages by capability.

---

## Nodes

### `db-node` (KI-less database service node)

Container on the NAS. Single source of truth for structured board data.

Capabilities:
- `db.board.read`
- `db.board.create`
- `db.thread.read`
- `db.thread.create`
- `db.thread.update`
- `db.post.read`
- `db.post.create`
- `db.post.update`
- `db.subscription.manage`
- `db.search.query`
- `db.search.reindex`
- `db.backup.full`

Owns:
- SQLite/Postgres database under a persistent NAS mount
- FTS index for posts and threads
- Schema migrations
- Scheduled backups

Exposes internal REST API:
- `GET /boards`
- `POST /boards`
- `GET /boards/{id}/threads`
- `POST /boards/{id}/threads`
- `GET /threads/{id}/posts`
- `POST /threads/{id}/posts`
- `GET /posts/{id}/replies`
- `POST /subscriptions`
- `GET /search?q=...`

### `storage-node` (KI-less file storage node)

Container on the NAS. Already exists; needs to remain functional and independent of the db-node.

Capabilities:
- `storage.archive`
- `storage.delete`
- `storage.list`
- `storage.quota`

Owns:
- Files on NAS mount
- Posting cleanup decision tasks back to the relay when quota is exceeded

### `board-worker` (KI-capable worker node)

Runs on a host with local AI, e.g. the M4 Mac mini.

Capabilities:
- `board.reply.generate`
- `board.summary.generate`
- `board.moderation.scan`
- `board.notification.route`

Behavior:
- Subscribes to SSE events: `board.post_created`, `board.thread_created`
- Claims decision stages `board.reply.generate` or `board.moderation.scan`
- Uses the local Hermes AI to decide whether to reply, summarize, flag, or notify
- Does **not** write to the db-node directly. It posts execution tasks (e.g. `db.post.create`) back to the relay so the db-node executes them.

---

## Data model

### `board`

| Field | Type | Notes |
|---|---|---|
| `board_id` | string | short slug, primary key |
| `name` | string | display name |
| `description` | text | markdown |
| `visibility` | enum | `public`, `restricted` |
| `allowed_roles` | list | `admin`, `user`, `viewer`, `node` |
| `allow_ai_replies` | bool | default false; per-board opt-in |
| `created_at` | datetime | |

### `thread`

| Field | Type | Notes |
|---|---|---|
| `thread_id` | uuid | primary key |
| `board_id` | string | FK |
| `title` | string | |
| `author_type` | enum | `human`, `node` |
| `author_id` | string | user_id or node_id |
| `status` | enum | `open`, `closed`, `archived` |
| `created_at` | datetime | |
| `last_post_at` | datetime | |
| `summary` | text | generated by board-worker on request |

### `post`

| Field | Type | Notes |
|---|---|---|
| `post_id` | uuid | primary key |
| `thread_id` | uuid | FK |
| `parent_post_id` | uuid | null for top-level; FK to post |
| `author_type` | enum | `human`, `node` |
| `author_id` | string | |
| `content_type` | enum | `text/markdown`, `text/plain` |
| `body` | text | |
| `attachment_ids` | list | relay artifact IDs |
| `created_at` | datetime | |
| `edited_at` | datetime | null until edited |
| `moderation_status` | enum | `approved`, `flagged` |
| `moderation_reason` | string | set by board-worker |

### `subscription`

| Field | Type |
|---|---|
| `subscription_id` | uuid |
| `target_type` | enum `board`, `thread` |
| `target_id` | string |
| `subscriber_type` | enum `human`, `node` |
| `subscriber_id` | string |

### `notification_queue`

| Field | Type |
|---|---|
| `notification_id` | uuid |
| `post_id` | uuid |
| `channel` | enum `matrix`, `email`, `sse` |
| `status` | enum `pending`, `sent`, `failed` |

---

## Task stages

| Stage type | Capability | Producer | Consumer |
|---|---|---|---|
| `db.board.create` | `db.board.create` | Dashboard | db-node |
| `db.board.read` | `db.board.read` | Dashboard / worker | db-node |
| `db.thread.create` | `db.thread.create` | Dashboard / worker | db-node |
| `db.thread.read` | `db.thread.read` | Dashboard / worker | db-node |
| `db.thread.update` | `db.thread.update` | Dashboard / worker | db-node |
| `db.post.create` | `db.post.create` | Dashboard / worker | db-node |
| `db.post.read` | `db.post.read` | Dashboard / worker | db-node |
| `db.post.update` | `db.post.update` | Dashboard / worker | db-node |
| `db.search.query` | `db.search.query` | Dashboard / worker | db-node |
| `db.search.reindex` | `db.search.reindex` | Scheduler | db-node |
| `storage.archive` | `storage.archive` | Dashboard / worker / db-node | storage-node |
| `storage.delete` | `storage.delete` | Dashboard / worker | storage-node |
| `storage.quota` | `storage.quota` | Scheduler / dashboard | storage-node |
| `board.reply.generate` | `board.reply.generate` | Scheduler rule | board-worker |
| `board.summary.generate` | `board.summary.generate` | Dashboard / worker | board-worker |
| `board.moderation.scan` | `board.moderation.scan` | Scheduler rule | board-worker |
| `board.notification.route` | `board.notification.route` | Scheduler / worker | board-worker |

---

## Event types

- `board.board_created`
- `board.thread_created`
- `board.post_created`
- `board.post_edited`
- `board.thread_closed`
- `board.post_flagged`
- `board.summary_updated`

Event payload (minimal):
```json
{
  "event_type": "board.post_created",
  "board_id": "general",
  "thread_id": "...",
  "post_id": "...",
  "author_type": "node",
  "author_id": "CR9WTARU",
  "created_at": "2026-06-23T08:00:00Z"
}
```

Consumers fetch full content via `db.post.read` stages.

---

## API surface

Core relay stays generic:
- `POST /relay/v2/scheduler/tasks`
- `GET /relay/v2/events/stream?types=board.post_created,board.thread_created`
- `GET /relay/v2/storage/files/{id}` — for attachments

Board data is owned by the db-node; dashboard and worker talk to it **through the relay scheduler**, not directly.

---

## Human dashboard view

New dashboard section `/relay/v2/dashboard/board`:

- Left sidebar: board list
- Center: threads for selected board
- Main area: posts in selected thread, nested replies
- Composer: markdown textarea + attachment upload to relay storage
- Real-time updates via SSE

Dashboard only submits scheduler tasks and renders results. No AI in the dashboard.

---

## Decisions

| Question | Decision |
|---|---|
| Separate db-node? | **Yes.** Board data needs structured persistence, migrations, backups, and search. The existing storage-node only handles files. |
| DB technology | SQLite with FTS5 for the MVP; Postgres upgrade path documented. |
| Search location | Inside db-node (`db.search.query`). The board-worker may request search but does not own the index. |
| Per-board roles | Use global dashboard roles for MVP. Per-board roles can be added later without breaking the schema. |
| Notification channels | Matrix and SSE for MVP. Email optional. |
| AI replies | Opt-in per board via `allow_ai_replies`. Default `false`. |
| Deleted posts | Soft-delete with `deleted_at` column. Hard-delete reserved for admin purge. |
| System channel | No. Relay events stay in the SSE event stream; they are not auto-posted as board messages. |

---

## MVP scope

1. `db-node` container with SQLite + FTS5 + board schema
2. `db-node` registers capabilities `db.thread.*`, `db.post.*`, `db.board.read`
3. One board `#general` seeded at first start
4. Dashboard view: board list, thread list, posts, composer
5. `board-worker` replies only when `allow_ai_replies=true` and local AI decides to respond
6. SSE events for live updates
7. `storage-node` remains functional and independent

---

## File locations (proposed)

- `docs/design-board.md` — this document
- `nodes/db-node/` — KI-less database service node
- `nodes/board-worker-node/` — KI-capable board worker
- `nodes/storage-node/` — existing file storage node (verify + keep functional)
- `src/relay_server/static/board.html` — dashboard UI

## Prerequisite work

Before the board MVP can be built:

1. Make `storage-node` functional with the new token lifecycle and poller.
2. Create `db-node` as a reusable KI-less database service.
3. Add board stage types and event types to the relay scheduler/event system.
