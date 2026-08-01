# TASKS.md — HIGH Security & Reliability Fixes

| ID    | Status | Notiz |
|-------|--------|-------|
| T-013 | done | Heartbeat Race Condition: TOCTOU in `mark_offline_nodes()` — `AND last_seen < ?` in UPDATE-WHERE-Klausel, nur tatsaechlich offline gesetzte Nodes feuern Events |
| T-014 | done | Audit Logging: `audit_logs`-Tabelle in `db.py` (Schema + Migration) + `log_audit_event()`-Hilfsfunktion, Logging in `admin_approve_node`, `admin_issue_node_token`, `admin_delete_node` |
| T-015 | done | EventBus Silent Drops: `_format_sse(event, dropped)` mit `X-Dropped`-Header, `subscriber_lagging`-Warn-Event bei 100 Drops via `_publish_internal()` (ohne History, keine Rekursion) |