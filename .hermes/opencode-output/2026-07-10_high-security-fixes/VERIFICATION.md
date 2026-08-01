# VERIFICATION.md

## Test-Suite

```bash
cd /home/felix/projects/ai-relay-service
RELAY_SESSION_SECRET="test-session-secret-do-not-use-in-production" \
  .venv/bin/python -m pytest tests/test_discovery.py tests/test_events.py \
  tests/test_dashboard.py tests/test_auth.py -q --tb=short 2>&1 | tail -5
```

**Ergebnis (Endzustand nach Task 3):**

```
57 passed, 42 warnings in 64.43s (0:01:04)
```

Nach jedem einzelnen Task wurden die jeweiligen Tests ausgefuehrt:

| Task | Suite | Ergebnis |
|------|-------|----------|
| Task 1 (T-013) | `tests/test_discovery.py` | 9 passed in 24.97s |
| Task 2 (T-014) | `tests/test_discovery.py` + `tests/test_dashboard.py` | 34 passed in 34.91s |
| Task 3 (T-015) | `tests/test_events.py` | 8 passed in 9.22s |
| Alle zusammen | `test_discovery.py` + `test_events.py` + `test_dashboard.py` + `test_auth.py` | 57 passed in 64.43s |

Hinweis: `RELAY_SESSION_SECRET` muss gesetzt sein (>= 32 Zeichen), da der
vorige CRITICAL-Fix T-012 den Token-Pepper fail-fast gemacht hat. Dies ist ein
vorgegebenes Test-Setup, nicht durch diese Aenderungen verursacht.

## Task 1: TOCTOU-Race-Verifikation

Die bestehenden Tests in `test_discovery.py` verifizieren:
- `test_heartbeat_timeout_marks_node_offline`: Node wird nach Heartbeat-Timeout
  als offline markiert (Zeile 169-179).
- `test_mark_offline_after_manual_last_seen`: `last_seen` wird manuell in die
  Vergangenheit gesetzt, `mark_offline_nodes()` markiert den Node offline
  (Zeile 417-427).

Beide Tests besttigen, dass die re-check-Logik funktioniert: Kandidaten werden
selektiert, das UPDATE prueft `last_seen < ?` erneut, und nur tatsaechlich
offline gesetzte Nodes werden zurueckgegeben und feuern Events.

## Task 2: Audit-Logging-Verifikation

Die `audit_logs`-Tabelle wird durch `_schema()` (neue DBs) und `_run_migrations()`
(bestehende DBs) angelegt. Die `log_audit_event()`-Funktion schreibt Eintraege.
Die `test_dashboard.py`- und `test_discovery.py`-Tests, die approve/token/delete
ausfuehren (z.B. `_http_worker_token` ruft `/admin/nodes/{id}/approve` auf),
verifizieren indirekt, dass die Audit-Logging-Aufrufe keine Exceptions werfen
und die Admin-Endpunkte weiterhin korrekt funktionieren (34 passed).

## Task 3: EventBus-Drop-Verifikation

- `test_event_bus_publish_sync_drop_counter`: Fuellt die Queue ueber, verifiziert
  dass `sub.dropped >= 5`. Der `dropped`-Zaehler wird weiterhin korrekt
  inkrementiert.
- `test_sse_stream_receives_event` / `test_sse_stream_filters_by_type`: SSE-Tests
  verifizieren, dass das `X-Dropped`-Header-Format die Event-Parsung nicht
  stoert (die Tests parsen `data:`-Zeilen und funktionieren weiterhin, da
  `X-Dropped` zwischen `event:` und `data:` eingefuegt wird und nur bei
  `dropped > 0` erscheint — bei diesen Tests ist `dropped == 0`).
- `test_event_bus_subscribe_and_publish` / `test_event_bus_unique_subscriber_ids_per_node`:
  Basis-Publish/Subscribe verifiziert, dass die `_event_bus`-Referenz am Subscriber
  und das `_publish_internal()`-System keine Nebeneffekte auf normale Events haben.

## Statische Verifikation der Einzelaenderungen

- **Task 1 (T-013):** `src/relay_server/core/discovery.py` —
  `mark_offline_nodes()` enthaelt jetzt `AND last_seen < ?` in der
  UPDATE-WHERE-Klausel. Nach dem UPDATE wird pro Kandidat der Status gelesen
  (`SELECT status FROM nodes WHERE node_id = ?`), um die tatsaechlich offline
  gesetzten IDs zu ermitteln. Events werden nur fuer diese gefeuert.
- **Task 2 (T-014):** `src/relay_server/core/db.py` — `audit_logs`-Tabelle in
  `_schema()` nach artifacts, Migration in `_run_migrations()`,
  `log_audit_event()`-Funktion am Dateiende. `src/relay_server/api/v2/admin.py` —
  `from relay_server.core.db import log_audit_event` import, `log_audit_event()`
  Aufrufe in `admin_approve_node`, `admin_issue_node_token`, `admin_delete_node`
  jeweils vor dem return.
- **Task 3 (T-015):** `src/relay_server/core/events.py` —
  `_Subscriber._event_bus`-Feld (default=None, init=False),
  `put_nowait()` feuert `subscriber_lagging` bei `dropped == 100` via
  `_event_bus._publish_internal()`. `subscribe()` setzt `sub._event_bus = self`
  und uebergibt `dropped` an `_format_sse()`. `_format_sse(event, dropped=0)`
  fuegt `X-Dropped: N`-Header ein wenn `dropped > 0`. `_publish_internal()`
  verteilt Events ohne History-Schreiben (vermeidet Rekursion).