# AI-Relay-Service — Project Status

## Overview

| Field | Value |
|-------|-------|
| **Version** | 2.0.0 |
| **Port** | 8788 |
| **Framework** | FastAPI + SQLite (WAL) |
| **Owner** | Ronny Pietschke |
| **Tests** | 93/93 passed (hard gate) |
| **Last Commits** | ed50b3e → e33a982 → f4aec86 → 4b624d2 |

## Phase Status

### Phase 1 — Core Infrastructure ✅
- [x] SQLite schema (nodes, tasks, task_stages, artifacts, users, groups, permissions, admin_seeds)
- [x] Additive DB migration system (no-downtime ALTER TABLE)
- [x] Config via `config.yaml` + `RELAY_*` env override
- [x] Node registry with collision-free ID minting (ADR-001, 8-char base32)

### Phase 2 — Auth & Security ✅
- [x] bcrypt (12 rounds) with legacy SHA-256 migration
- [x] 4 token types: admin seed (`adm_`), bootstrap (`bs_`), temporary (`tp_`), runtime (`rt_`)
- [x] Token rotation — single valid runtime token per node
- [x] Registration secret recovery (12h TTL)
- [x] RBAC: users, groups, permissions, roles (superadmin / admin / user)
- [x] CSRF protection (double-submit cookie)
- [x] Rate limiting on dashboard (SlowAPI)
- [x] Security headers (HSTS, X-Content-Type-Options, X-Frame-Options)
- [x] Force password change on first login
- [x] Common password blocklist (20 entries)

### Phase 3 — Task Lifecycle ✅
- [x] Multi-stage DAG tasks
- [x] `POST /scheduler/tasks` — create with stages
- [x] `POST /scheduler/claim` — claim next pending stage
- [x] `POST /scheduler/stages/{id}/complete` — complete with result
- [x] Priority queue (0–10)
- [x] Configurable timeout per task
- [x] Auto-complete remaining stages on final completion

### Phase 4 — Monitoring & Events ✅
- [x] SSE event stream (`/events/stream?node=&types=`)
- [x] Event types: node_online, node_offline, task_created, stage_claimed, stage_completed, presence_changed, artifact_created
- [x] In-memory EventBus (500 history, backpressure-safe)
- [x] Presence system (status, mood, activity, progress, ETA)
- [x] Dashboard with live SSE, RBAC, node approval
- [x] Discovery query with 5 simultaneous filters

### Phase 5 — Nodes & Integration ✅
- [x] Generic Worker Node — heartbeat 8s, SIGHUP reload, mtime-check, exponential backoff (5 retries, max 60s), graceful shutdown
- [x] Storage Node — archive, delete, list, quota with auto-cleanup task posting
- [x] Generic Agent Poller — JSON-configurable, credential refresh, 401/403 auto-recovery

### Phase 6 — Open Items ⏳
- [ ] Artifact upload/download from worker side
- [ ] Credential-refresh daemon (P0)
- [ ] YAML schema validation for capabilities.yaml
- [x] Node README improvement feedback reviewed

---

## Code Review Summary (OpenCode)

| # | File | Severity | Finding | Recommendation |
|---|------|----------|---------|----------------|
| F1 | `discovery.py:98` | Medium | `config_filter` JSON parse with no try/except | Add `try/except JSONDecodeError` |
| F2 | `poller.py:211` | Low | `fromisoformat()` fails on `Z`-suffix pre-3.11 | `.replace('Z','+00:00')` or use `dateutil` |
| F3 | `scheduler.py:205` | Info | `claim_stage` matches only `pending` | Correct per spec — `online` = already running |
| F4 | `models/capability.py` + `common/capability.py` | Medium | Duplicate `CapabilityInputSchema` (Pydantic vs dataclass) | Consolidate into shared package |
| F5 | `worker.py` vs `poller.py` | Low | Task-timeout inconsistent (24s vs 600s configurable) | Centralize via config, raise worker default |
| F6 | All docs | Task | German docs need English translation | In progress — see below |

**Security Audit: PASS** — bcrypt migration, timing-safe compare, CSRF, CORS, rate-limiting, input validation all verified. No critical findings.

## Architecture

```
┌──────────────────────────────────────────────┐
│  API v2 Router                               │
│  /auth · /discovery · /scheduler · /storage  │
│  /presence · /events · /dashboard · /admin   │
├──────────────────────────────────────────────┤
│  Core Services                               │
│  auth · discovery · scheduler · artifacts    │
│  · presence · events · session · users · db  │
├──────────────────────────────────────────────┤
│  SQLite (WAL, FK, Row factory)               │
│  nodes · tasks · stages · artifacts          │
│  · users · groups · permissions · seeds      │
├──────────────────────────────────────────────┤
│  Node Clients                                │
│  worker (typer) · storage-node · poller      │
└──────────────────────────────────────────────┘
```