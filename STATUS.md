# AI-Relay-Service — Project Status

## Overview

| Field | Value |
|-------|-------|
| **Version** | 2.0.0 |
| **Port** | 8788 |
| **Framework** | FastAPI + SQLite (WAL) |
| **Owner** | Ronny Pietschke |
| **Tests** | 205/205 passed |
| **Last Commits** | ed50b3e → e33a982 → f4aec86 → 4b624d2 → 2222f4b → 7ba5aaf → 1fcf787 → 6a9c83e → 09d0a8c → 122dca6 → c96d71e → f4827c4 → bc70188 → 85a7971 |

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

### Phase 6 — Hardening & Cleanup ✅
- [x] Artifact upload/download from worker side (T-001)
- [x] Worker-seitiger Token-Refresh (T-002)
- [x] YAML schema validation for capabilities.yaml (T-003)
- [x] Node README improvement feedback reviewed
- [x] SQLite Lock Contention (T-016)
- [x] Task Timeout enforced (T-017)
- [x] Poller Hard Exit (T-018)
- [x] Inconsistent Logging Levels (T-019)
- [x] Dashboard CSRF Policy dokumentiert (T-020)
- [x] Missing Type Hints (T-021)
- [x] Secrets in Logs vermeiden (T-024)
- [x] Dashboard-Token TTL verkürzen (T-025)
- [x] Capabilities normalisieren (T-026)
- [x] validate_token synchroner DELETE → Token-Cleanup-Watchdog (T-027)
- [x] CRITICAL: Relay stürzt nach ~20s ab — RELAY_SESSION_SECRET fehlte (T-028)
- [x] LOW: Bootstrap-Seite Copy-Button + Login-Link (T-029)
- [x] Dokumentation: Server + Node-CLI + Node-Setup überarbeitet (T-030)
- [x] Dokumentation: Komplette Restrukturierung (T-031)
- [x] GitHub Review Findings behoben (T-032) — 11 Findings
- [x] Zweiter GitHub-Review behoben (T-033) — 22 Findings
- [x] `description`-Field in capability_loader ergänzt

### Phase 7 — CLI-Erweiterungen & Bugfixes ✅
- [x] `node-cli capabilities server` — Server-Capability-Query (T-035)
- [x] Capability-Availability-Bug in `get_capabilities()` gefixt (T-036)
- [x] Cross-platform load normalisation: `(load_avg / cpu_count) * 100` (T-037)

### Phase 8 — Routing & Adressierung ✅
- [x] `owner_node_id` in `claim_stage()` respektieren — Tasks lassen sich an einen bestimmten Node pinnen (T-046)
- [x] `node-cli task submit --owner <node_id>` — Owner-Flag im Client (T-046)

---

## Code Review Summary (historical — all findings resolved)

> The F1–F6 findings below are historical. All of them have been addressed in
> later commits; this table is kept only for traceability.

| # | File | Severity | Finding | Resolution |
|---|------|----------|---------|------------|
| F1 | `discovery.py:98` | Medium | `config_filter` JSON parse with no try/except | ✅ Fixed |
| F2 | `poller.py:211` | Low | `fromisoformat()` fails on `Z`-suffix pre-3.11 | ✅ Fixed |
| F3 | `scheduler.py:205` | Info | `claim_stage` matches only `pending` | ✅ Correct per spec |
| F4 | `models/capability.py` + `common/capability.py` | Medium | Duplicate `CapabilityInputSchema` | ✅ Consolidated |
| F5 | `worker.py` vs `poller.py` | Low | Task-timeout inconsistent | ✅ Centralized via config |
| F6 | All docs | Task | German docs need English translation | ✅ Done |

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
│  node-cli · storage-node                    │
└──────────────────────────────────────────────┘
```