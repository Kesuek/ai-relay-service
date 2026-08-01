# Plan: Phase 11 — Claim-Retry-Schutz & Offline-Erkennung (T-060 + T-061)

## Ziel
Zwei Bugs schliessen:
- **T-060:** Daemon claimt Tasks wiederholt → RAM-Overflow (Handler exit 0 trotz Fehler → Stage pending → reclaim)
- **T-061:** Node claimt Stage, Handler startet nicht / Node stirbt → Stage bleibt ewig pending

## Änderungen

### 1. DB Migration — `retry_count` in `task_stages`
**Datei:** `src/relay_server/core/db.py`
- Neue Migration: `ALTER TABLE task_stages ADD COLUMN retry_count INTEGER DEFAULT 0;`
- In `_run_migrations()` ergänzen (analog zu bestehenden Migrationen)

### 2. `release_expired_claims()` → `release_or_fail_claims()`
**Datei:** `src/relay_server/core/scheduler.py`
- `release_expired_claims()` umbenennen in `release_or_fail_claims()`
- Bei Release: `retry_count += 1`
- Wenn `retry_count >= settings.max_retries` (default 2 → 3 Versuche total): Stage als `failed` markieren statt `pending`
- Task auf `failed` setzen wenn alle Stages failed sind
- Events: `stage_failed`, `task_failed`
- `_stage_row_to_dict()`: `retry_count` aufnehmen

### 3. `mark_offline_nodes()` — claimed Stages failen
**Datei:** `src/relay_server/core/discovery.py`
- Nachdem Node als offline markiert: alle `claimed` Stages dieses Nodes als `failed` setzen
- Task auf `failed` setzen wenn alle Stages failed sind
- Events: `stage_failed`, `task_failed`

### 4. Config — `max_retries` existiert bereits
**Datei:** `src/relay_server/config.py`
- `max_retries: int = 2` ist schon da (Zeile 47) — kein Change nötig

### 5. Watchdogs in `main.py` anpassen
**Datei:** `src/relay_server/main.py`
- `_claim_ttl_watchdog()`: `Scheduler.release_expired_claims` → `Scheduler.release_or_fail_claims`
- `_heartbeat_watchdog()`: bleibt gleich, aber `mark_offline_nodes()` failt jetzt claimed Stages

### 6. Daemon: `_failed_tasks` Tracking
**Datei:** `nodes/common/node_cli.py`
- `Daemon.__init__()`: `self._failed_tasks: dict[str, int] = {}`
- `_run_stage()`: bei Fehler (Exception oder complete-Fehler) → `_failed_tasks[task_id] += 1`
- `_claim_loop()`: vor claim prüfen ob `_failed_tasks.get(task_id, 0) >= max_retries` → überspringen
- `max_retries` aus Config lesen (oder hardcoded 3)

### 7. Handler-Contract schärfen
**Datei:** `docs/node/capabilities.md`
- Klarstellen: Handler MUSS bei Fehlern exit != 0 returnen
- Handler DARF bei exit 0 nur valides JSON auf stdout schreiben
- `handler_runner.py` Docstring aktualisieren

### 8. Tests
**Datei:** `tests/test_scheduler.py`
- Test: `release_or_fail_claims()` failt Stage nach N Rücksetzungen
- Test: `mark_offline_nodes()` failt claimed Stages
- Test: Task wird auf `failed` gesetzt wenn alle Stages failed

**Datei:** `tests/nodes/test_node_cli.py`
- Test: Daemon überspringt Task nach N Fehlversuchen

## Reihenfolge
1. DB Migration (`db.py`)
2. `release_or_fail_claims()` (`scheduler.py`)
3. `mark_offline_nodes()` failt claimed Stages (`discovery.py`)
4. Watchdogs (`main.py`)
5. Daemon `_failed_tasks` (`node_cli.py`)
6. Doku (`capabilities.md`, `handler_runner.py`)
7. Tests
8. `pytest` — alle bestehenden Tests müssen grün bleiben
