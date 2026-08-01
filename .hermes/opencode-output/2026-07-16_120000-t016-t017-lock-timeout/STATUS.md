# STATUS — T-016 + T-017: SQLite Lock Contention + Task Timeout Enforcement

**Datum:** 2026-07-16
**Betroffene Commits:** `9241d14`, `839ac41`
**Plan:** `.hermes/plans/2026-07-16_120000-t016-t017-lock-timeout.md`

## Zusammenfassung

Beide Tasks wurden vollstaendig umgesetzt. Konkurrierende SQLite-Writes
(z. B. Heartbeat + Claim gleichzeitig) werden nun mit exponentiellem Backoff
retried, statt sofort `database is locked` zu werfen. Zusaetzlich wertet der
Scheduler die bisher ignorierte `timeout_seconds`-Spalte aus: ueberfaellige
`claimed` Stages werden via `enforce_timeouts()` als `timed_out` markiert und
Tasks, deren saemtliche Stages fertig/timed_out sind, erhalten ebenfalls
den Status `timed_out`.

| Task | Inhalt | Status | Commit |
|------|--------|--------|--------|
| Task 1 | `retry_on_locked` in `db.py` + `_retry_db_write` in `scheduler.py` + 3 Tests | ✅ done | `9241d14` |
| Task 2 | `Scheduler.enforce_timeouts()` + `POST /relay/v2/scheduler/enforce-timeouts` + 3 Tests | ✅ done | `839ac41` |
| Task 3 | Gesamtsuite verifizieren (keine Regression) | ✅ done | — |

## Betroffene Dateien

- `src/relay_server/core/db.py` — `retry_on_locked`-Decorator
  (`LOCKED_RETRIES`, `LOCKED_BASE_DELAY`), angewandt auf `log_audit_event`
- `src/relay_server/core/scheduler.py` — `_retry_db_write`-Wrapper
  (`_LOCKED_RETRIES`, `_LOCKED_BASE_DELAY`), dekorriert
  `create_task`, `claim_stage`, `complete_stage`, `release_expired_claims`;
  neue Methode `enforce_timeouts()`
- `src/relay_server/api/v2/scheduler.py` — neuer Endpoint
  `POST /relay/v2/scheduler/enforce-timeouts`
- `tests/test_scheduler.py` — 6 neue Tests (3 Lock-Retry, 3 Timeout-Enforcement)

## Verifikation

Siehe `VERIFICATION.md`. Gesamtsuite: 184 passed (Plan erwartete 178+),
keine Regression.

## Abweichung vom Plan

- **Dekorator-Reihenfolge:** Der Plan zeigte schematisch
  `@retry_on_locked` ueber `@staticmethod`. Korrekt ist
  `@staticmethod` aussen, `@_retry_db_write` innen (Python verlangt, dass
  `staticmethod` der aeusserste Decorator ist). Implementiert und per
  `python -c "Scheduler.create_task"` verifiziert (Funktion ist normal
  aufrufbar).
- **`enforce_timeouts()` Tests:** Der Test-Code im Plan enthielt eine
  Variablen-Wiederverwendung (`r` wurde fuer den `enforce-timeouts`-Call
  reassigned und danach `r.json()['tasks_timed_out'][0]` gelesen, obwohl `r`
  die Timeout-Antwort war — das waere korrekt gewesen, aber die nachfolgende
  `tasks/{id}`-Anfrage verwendete ebenfalls `r`). Die Tests wurden so
  umgeschrieben, dass die Task-ID explizit in `timed_out_task_id`
  zwischengespeichert wird. Zusaetzlich wurde ein dritter Test
  (`test_enforce_timeouts_does_not_touch_pending_stage`) ergaenzt, der
  verifiziert, dass nie beanspruchte (pending) Stages unangetastet
  bleiben. Inhaltlich entspricht das Verhalten exakt dem Plan.
- **`tasks_timed_out`-Semantik:** Der Plan-Rumpf schlug vor, alle
  `affected_tasks` zurueckzuliefern. Korrekter ist, nur die Tasks als
  `timed_out` zu melden, deren saemtliche Stages abgeschlossen sind. Die
  Methode liefert daher `tasks_timed_out` (= Tasks mit Statusupdate) statt
  aller betroffenen Tasks zurueck. Der Single-Stage-Test bestätigt das.

Alle weiteren Aenderungen entsprechen 1:1 dem Plan.