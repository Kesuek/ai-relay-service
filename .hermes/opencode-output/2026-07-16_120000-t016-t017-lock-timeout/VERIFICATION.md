# VERIFICATION.md

## Test-Suite (betroffene Module)

```bash
cd /home/felix/projects/ai-relay-service
.venv/bin/python -m pytest tests/test_scheduler.py -v 2>&1 | tail -15
```

**Ergebnis (Endzustand nach Task 2):**

```
11 passed, 7 warnings in 15.12s
```

Nach jedem einzelnen Task wurde die jeweilige Suite ausgefuehrt und blieb gruen:

| Task | Suite | Ergebnis |
|------|-------|----------|
| Task 1 | `test_scheduler.py::test_db_write_*` (3 Tests) | 3 passed |
| Task 1 | `test_scheduler.py` (komplett nach Task 1) | 8 passed |
| Task 2 | `test_scheduler.py::test_enforce_timeouts_*` (3 Tests) | 3 passed |
| Task 2 | `test_scheduler.py` (komplett nach Task 2) | 11 passed |

## Gesamtsuite (Regressionstest)

```bash
cd /home/felix/projects/ai-relay-service
.venv/bin/python -m pytest tests/ -q --ignore=tests/test_zeroconf.py -x --tb=short 2>&1 | tail -5
```

**Ergebnis:**

```
184 passed, 42 warnings in 115.62s (0:01:55)
```

Plan erwartete 178+ passed — 184 passed, keine Regression, kein neuer
Testfehler.

## Task 1: Lock-Retry — Einzelnachweis

```bash
.venv/bin/python -m pytest \
  tests/test_scheduler.py::test_db_write_retries_on_locked \
  tests/test_scheduler.py::test_db_write_raises_after_exhausted_retries \
  tests/test_scheduler.py::test_db_write_does_not_retry_non_lock_error -v
```

```
3 passed
```

- `test_db_write_retries_on_locked`: 3 `database is locked`-Wuerfe, beim
  3. Versuch `"ok"`; `call_count == 3`.
- `test_db_write_raises_after_exhausted_retries`: 5× `database is locked`
  -> `sqlite3.OperationalError`, `call_count == _LOCKED_RETRIES` (5).
- `test_db_write_does_not_retry_non_lock_error`: `"no such table: foo"`
  propagiert sofort, `call_count == 1` (kein Retry bei nicht-Lock-Fehlern).

## Task 2: Timeout-Enforcement — Einzelnachweis

```bash
.venv/bin/python -m pytest \
  tests/test_scheduler.py::test_enforce_timeouts_marks_overdue_stages \
  tests/test_scheduler.py::test_enforce_timeouts_noop_when_none_overdue \
  tests/test_scheduler.py::test_enforce_timeouts_does_not_touch_pending_stage -v
```

```
3 passed
```

- `test_enforce_timeouts_marks_overdue_stages`: Single-Stage-Task mit
  `timeout_seconds=1` wird beansprucht, `claimed_at` manuell um 1h
  zurueckdatiert, `enforce-timeouts` markiert die Stage als `timed_out` und
  (da alle Stages fertig/timed_out) auch den Task.
- `test_enforce_timeouts_noop_when_none_overdue`: Leere DB ->
  `{"stages_timed_out": [], "tasks_timed_out": []}`.
- `test_enforce_timeouts_does_not_touch_pending_stage`: Task mit
  pending (ungeclaimter) Stage bleibt unangetastet; Task-Status bleibt
  `pending`.

## Statische Verifikation der Einzelaenderungen

- **Task 1, db.py:** `retry_on_locked` nach den Imports eingefuegt;
  `@retry_on_locked` ueber `log_audit_event`.
- **Task 1, scheduler.py:** `_retry_db_write` nach den Imports; die vier
  Schreib-Static-Methoden mit `@staticmethod` aussen und `@_retry_db_write`
  innen. Verifiziert via
  `python -c "from relay_server.core.scheduler import Scheduler; print(Scheduler.create_task, Scheduler.claim_stage, Scheduler.complete_stage, Scheduler.release_expired_claims)"`
  -> vier normale Funktionsobjekte (kein statmethod-Descriptor-Leak).
- **Task 2, scheduler.py:** `enforce_timeouts()` nach `release_expired_claims`
  eingefuegt. Query `datetime(claimed_at, '+' || timeout_seconds || ' seconds') < ?`,
  Stage-Update auf `timed_out`, pro Task `remaining`-Count, Task-Update auf
  `timed_out` mit `completed_at`, `event_bus.publish_sync` fuer
  `stage_timed_out` und `task_timed_out`.
- **Task 2, api/v2/scheduler.py:** `POST /enforce-timeouts` nach
  `/artifacts/{artifact_id}` DELETE ergaenzt; nutzt
  `get_approved_context` (gleicher Guard wie alle Scheduler-Endpoints);
  Rueckgabe `Scheduler.enforce_timeouts()`.