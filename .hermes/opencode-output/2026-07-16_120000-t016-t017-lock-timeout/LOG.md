# LOG.md — Abarbeitung T-016 + T-017 (SQLite Lock Contention + Task Timeout Enforcement)

**Start:** 2026-07-16
**Plan:** `.hermes/plans/2026-07-16_120000-t016-t017-lock-timeout.md`

## Ablauf

1. **Kontext-Check:** Vor der ersten Aenderung wurden die im Plan genannten
   Code-Stellen gelesen und gegen den tatsaechlichen Stand abgeglichen:
   `db.py` (Imports, `get_conn`, `log_audit_event` als einzige freie
   Write-Funktion), `scheduler.py` (Imports, vier Schreib-Static-Methoden
   `create_task`/`claim_stage`/`complete_stage`/`release_expired_claims`,
   `release_expired_claims` als Positionsmarker fuer `enforce_timeouts`),
   `api/v2/scheduler.py` (Imports incl. `AuthContext`, `get_approved_context`,
   Endpoint-Reihenfolge), `tests/test_scheduler.py` (Fixtures `_seed_admin`/
   `_register`/`client`, keine `sqlite3`/`functools`-Imports bislang). Alle
   Stellen stimmten mit dem Plan ueberein.

2. **Task 1, Step 1 (db.py-Decorator):** `functools`/`time`-Imports ergaenzt,
   `LOCKED_RETRIES=5`, `LOCKED_BASE_DELAY=0.05` und `retry_on_locked`
   nach den Imports eingefuegt; `@retry_on_locked` ueber `log_audit_event`.

3. **Task 1, Step 2 (scheduler.py-Wrapper):** `functools`/`sqlite3`/`time`
   ergaenzt, `_retry_db_write` mit `_LOCKED_RETRIES`/`_LOCKED_BASE_DELAY`
   definiert. Die vier Schreib-Static-Methoden erhielten `@staticmethod`
   (aussen) + `@_retry_db_write` (innen) — die im Plan schematisch
   skizzierte Reihenfolge (`@retry_on_locked` ueber `@staticmethod`) wurde
   korrigiert, weil `staticmethod` der aeusserste Decorator sein muss.
   Verifiziert via `python -c "Scheduler.create_task"` (Funktion ist
   normal aufrufbar, kein statmethod-Descriptor-Leak).

4. **Task 1, Step 3+4 (Tests + Verify):** 3 Tests in `test_scheduler.py`
   ergaenzt: `test_db_write_retries_on_locked` (3 Versuche, 3. liefert
   `"ok"`), `test_db_write_raises_after_exhausted_retries` (5× lock ->
   raise, `call_count == _LOCKED_RETRIES`), und zusaetzlich
   `test_db_write_does_not_retry_non_lock_error` (`"no such table"` wird
   nicht retried, `call_count == 1`). pytest (3 Tests): 3 passed.
   Import-Check fuer `db.py` (kein Circular Import): OK.

5. **Task 1, Step 5 (Commit):** `git commit -m "fix(db): add retry-on-locked
   decorator for SQLite contention"` -> `9241d14`.

6. **Task 2, Step 1 (enforce_timeouts):** Methode nach
   `release_expired_claims` eingefuegt: SELECT ueberfaellige `claimed`
   Stages via `datetime(claimed_at, '+' || timeout_seconds || ' seconds')
   < ?`, UPDATE auf `timed_out`, pro Task `remaining`-Count, Task-Update
   auf `timed_out` mit `completed_at`, Events `stage_timed_out`/
   `task_timed_out` via `event_bus.publish_sync`. Rueckgabe
   `{"stages_timed_out": [...], "tasks_timed_out": [...]}` wobei
   `tasks_timed_out` nur Tasks enthaelt, die den Statuswechsel erhielten
   (Plankorrigatur). `@staticmethod` + `@_retry_db_write` analog zu den
   anderen Schreibmethoden. `python -c "Scheduler.enforce_timeouts"`: OK.

7. **Task 2, Step 2 (API-Endpoint):** `POST /enforce-timeouts` nach
   `/artifacts/{artifact_id}` DELETE ergaenzt, nutzt
   `get_approved_context` (gleicher Guard wie alle Scheduler-Endpoints).

8. **Task 2, Step 3+4+5 (Tests + Verify):** 3 Tests in `test_scheduler.py`:
   `test_enforce_timeouts_marks_overdue_stages` (Single-Stage-Task,
   `timeout_seconds=1`, claimed, `claimed_at` manuell 1h zurueckdatiert,
   enforce -> Stage `timed_out` + Task `timed_out`),
   `test_enforce_timeouts_noop_when_none_overdue` (leer -> beide Listen
   leer), zusaetzlich `test_enforce_timeouts_does_not_touch_pending_stage`
   (pending Stage unangetastet, Task bleibt `pending`). Der Plan-Testcode
   wurde auf explizite `timed_out_task_id`-Zwischenspeicherung
   umgeschrieben (kein `r`-Reuse). pytest (3 Tests): 3 passed. Komplette
   `test_scheduler.py`: 11 passed.

9. **Task 2, Step 6 (Commit):** `git commit -m "feat(scheduler): add
   enforce_timeouts() for overdue stages/tasks"` -> `839ac41`.

10. **Task 3 (Gesamtsuite):** `pytest tests/ -q --ignore=tests/test_zeroconf.py
    -x --tb=short`: 184 passed in 1m55s (Plan erwartete 178+). Keine
    Regression.

## Endzustand

184 passed (gesamte Suite), 42 warnings. 11 passed in `test_scheduler.py`
(5 bestehend + 6 neu). Kein Regressions- oder neu eingefuehrter
Testfehler.

## Commits

- `9241d14` fix(db): add retry-on-locked decorator for SQLite contention
- `839ac41` feat(scheduler): add enforce_timeouts() for overdue stages/tasks

## Output

- `STATUS.md`
- `TASKS.md`
- `DECISIONS.md`
- `VERIFICATION.md`
- `LOG.md` (diese Datei)