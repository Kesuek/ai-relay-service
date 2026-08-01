# LOG.md — Abarbeitung HIGH Security & Reliability Fixes

**Start:** 2026-07-10
**Plan:** `.hermes/plans/2026-07-10_high-security-fixes.md`

## Ablauf

1. **Kontext-Check:** Vor der ersten Aenderung wurden alle im Plan genannten
   Code-Stellen gelesen und gegen den tatsaechlichen Stand abgeglichen:
   - `discovery.py` Zeilen 301-327 (`mark_offline_nodes` mit SELECT-then-UPDATE
     ohne re-check)
   - `db.py` `_schema()` (keine audit_logs-Tabelle), `_run_migrations()`
     (keine audit_logs-Migration)
   - `events.py` (`_Subscriber` ohne `_event_bus`, `_format_sse` ohne dropped,
     keine `_publish_internal`)
   - `api/v2/admin.py` (keine audit-Logging-Aufrufe in approve/token/delete)
   - `tests/test_discovery.py`, `tests/test_events.py`
   - `models/__init__.py` AuthContext (Felder: node_id, node_name, user_id,
     username, groups, role, status)
   Alle Stellen stimmten mit dem Plan ueberein.

2. **Task 1 (T-013, Heartbeat Race Condition — TOCTOU):**
   - `mark_offline_nodes()` in `discovery.py` umgebaut:
     - SELECT liefert `candidate_ids` (statt `offline_ids`)
     - UPDATE enthaelt `AND last_seen < ?` in der WHERE-Klausel
     - Nach UPDATE: pro Kandidat Status lesen, nur offline-Status -> Events
   - pytest `tests/test_discovery.py`: 9 passed (24.97s).
   - Commit `d4ac1ec`.

3. **Task 2 (T-014, Audit Logging):**
   - `import secrets` + `from typing import Optional` in `db.py` hinzugefuegt.
   - `audit_logs`-Tabelle in `_schema()` nach artifacts eingefuegt
     (mit Indexes auf `created_at` und `actor_id`).
   - Migration in `_run_migrations()` fuer bestehende DBs (table_names-Check).
   - `log_audit_event()`-Hilfsfunktion am Ende von `db.py` hinzugefuegt.
   - In `admin.py`: `from relay_server.core.db import log_audit_event` import.
   - `log_audit_event()` in `admin_approve_node` (action=`node.approve`,
     details=`role={body.role}`), `admin_issue_node_token`
     (action=`node.issue_token`), `admin_delete_node` (action=`node.delete`)
     jeweils vor dem return.
   - pytest `tests/test_discovery.py` + `tests/test_dashboard.py`: 34 passed
     (34.91s).
   - Commit `4d9e303`.

4. **Task 3 (T-015, EventBus Silent Drops):**
   - `_Subscriber` um `_event_bus`-Feld erweitert (default=None, init=False).
   - `put_nowait()` feuert `subscriber_lagging`-Event bei `dropped == 100`
     via `self._event_bus._publish_internal()`.
   - `subscribe()`: `sub._event_bus = self` gesetzt, `dropped` aus Subscriber
     an `_format_sse()` uebergeben.
   - `_format_sse(event, dropped=0)`: fuegt `X-Dropped: N`-Header ein wenn
     `dropped > 0` (zwischen `event:` und `data:`).
   - `_publish_internal()`: verteilt Events ohne History-Schreiben (vermeidet
     Rekursion, da `subscriber_lagging` selbst keine History erzeugt).
   - pytest `tests/test_events.py`: 8 passed (9.22s).
   - Commit `53a7884`.

5. **Endverifikation:** Vollstaendige Suite:
   ```
   57 passed, 42 warnings in 64.43s
   ```
   (test_discovery.py + test_events.py + test_dashboard.py + test_auth.py)

## Endzustand

57 passed, 42 warnings. Kein Regressions- oder neu eingefuehrter Testfehler.
Drei Commits, einer pro Task.

## Commits

```
53a7884 fix(events): expose dropped counter in SSE stream, add subscriber_lagging warning event
4d9e303 feat(audit): add audit_logs table and log admin actions (approve, token, delete)
d4ac1ec fix(discovery): TOCTOU race in mark_offline_nodes — re-check last_seen in UPDATE WHERE clause
```

## Output

- `STATUS.md`
- `TASKS.md`
- `DECISIONS.md`
- `VERIFICATION.md`
- `LOG.md` (diese Datei)