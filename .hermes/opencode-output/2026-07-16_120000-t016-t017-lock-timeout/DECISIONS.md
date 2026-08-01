# DECISIONS.md

## 2026-07-16: T-016 + T-017 — Retry-Decorator für SQLite Lock Contention + Task Timeout Enforcement

**Entscheidung:** Zwei Tasks aus dem Project Board umgesetzt:

- **T-016 (Retry-Decorator für SQLite Lock Contention):** Konkurrierende
  SQLite-Writes werfen unter WAL-Mode weiterhin `database is locked`, sobald
  der Write-Latch gehalten wird (z. B. Heartbeat-Update + Stage-Claim
  gleichzeitig). Ein `retry_on_locked`-Decorator in `db.py` (angewandt auf
  `log_audit_event`) und ein funktionsidentischer `_retry_db_write`-Wrapper
  in `scheduler.py` (angewandt auf die vier Schreib-Static-Methoden
  `create_task`, `claim_stage`, `complete_stage`, `release_expired_claims`)
  fangen `sqlite3.OperationalError("database is locked")` ab und wiederholen
  den Aufruf mit exponentiellem Backoff (50ms → 100ms → 200ms → 400ms →
  800ms, max. 5 Versuche ≈ 1.5s Gesamt). Andere `OperationalError`-Meldungen
  werden ungefiltert weitergeworfen. Der Duplikat-Code in beiden Modulen
  ist bewusst gewaehlt, da `scheduler.py` die Connection selbst verwaaltet
  und ein Cross-Modul-Import des Decorators die Abhaengigkeitsrichtung
  umdrehen wuerde.
- **T-017 (enforce_timeouts):** Die `timeout_seconds`-Spalte in `tasks` und
  `task_stages` wurde bislang gespeichert, aber nie ausgewertet —
  `release_expired_claims()` pruefte nur das Claim-TTL
  (`claim_expires_at`), nicht den Task-Timeout. Die neue Methode
  `Scheduler.enforce_timeouts()` findet `claimed` Stages, bei denen
  `datetime(claimed_at, '+' || timeout_seconds || ' seconds') < now` gilt,
  markiert sie als `timed_out` und prueft pro betroffenem Task, ob noch
  Stages ausserhalb `completed`/`timed_out` existieren. Ist das nicht der
  Fall, wird der Task ebenfalls `timed_out` gesetzt (und `completed_at`
  gesetzt). Es werden `stage_timed_out`- und `task_timed_out`-Events
  gepublished. Ein manueller Trigger-Endpoint
  `POST /relay/v2/scheduler/enforce-timeouts` gibt `{"stages_timed_out":
  [...], "tasks_timed_out": [...]}` zurueck (nur die Tasks, die tatsaechlich
  den Statuswechsel erhalten haben, nicht alle betroffenen Tasks).

**Grund:** SQLite-Lock-Contention trat im Betrieb sporadisch auf und
fuehrte zu fehlschlagenden Claims/Audits; der Backoff-Retry ist die
SQLite-typische Loesung, ohne auf ein externes Lock zu wechseln. Die
Timeout-Spalte war ein totes Feature: Worker, die nach einem Claim
abstuertzten, konnten Stages ewig blockieren, weil nur das Claim-TTL
(60s Default) zurueckgesetzt wurde, aber nie der konfigurierte Task-Timeout.

**Betroffene Files:** `src/relay_server/core/db.py`,
`src/relay_server/core/scheduler.py`, `src/relay_server/api/v2/scheduler.py`,
`tests/test_scheduler.py`
**Betroffene Tasks:** T-016, T-017

---

## Abweichung vom Plan

Siehe `STATUS.md` Abschnitt "Abweichung vom Plan":

- Decorator-Reihenfolge korrigiert (`@staticmethod` aussen, `_retry_db_write`
  innen).
- `enforce_timeouts`-Test auf explizite Variablenzwischenspeicherung
  umgeschrieben, dritter Test (`does_not_touch_pending_stage`) ergaenzt.
- `tasks_timed_out` liefert nur Tasks mit Statuswechsel statt aller
  betroffenen Tasks (Plankorrigatur).