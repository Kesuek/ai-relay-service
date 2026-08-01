# Plan: Phase 9+12 — Maintenance-System + Watchdogs (T-049, T-050, T-063)

## Ziel
Drei Watchdogs bauen, die im Server als asyncio-Tasks laufen:
- **T-049:** Artifact Cleanup — verwaiste Artifakte löschen (keine Task-Referenz mehr)
- **T-050:** Maintenance-System — zentraler `MaintenanceScheduler` der alle Watchdogs bündelt
- **T-063:** Orphaned-Stage-Watchdog — `pending` Stages deren Capability von keinem Node heartbeatet wird → `failed`

## Änderungen

### 1. `src/relay_server/core/maintenance.py` — NEU
Zentraler `MaintenanceScheduler` als Singleton. Bündelt alle periodischen Tasks:

```python
class MaintenanceScheduler:
    def __init__(self):
        self._tasks: dict[str, dict] = {}  # name -> {interval, func, last_run}

    def register(self, name: str, func: Callable, interval_seconds: int) -> None
    def unregister(self, name: str) -> None
    def run_due(self) -> dict[str, Any]  # führt fällige Tasks aus, returns {name: result}
    def run_all(self) -> dict[str, Any]   # führt alle Tasks sofort aus
    def status(self) -> list[dict]        # name, interval, last_run, next_run
```

Tasks die registriert werden:
- `heartbeat_watchdog` — `mark_offline_nodes()` (10s)
- `claim_ttl_watchdog` — `release_or_fail_claims()` (60s)
- `token_cleanup` — expired tokens löschen (3600s)
- `artifact_cleanup` — verwaiste Artifakte löschen (3600s, T-049)
- `chunked_upload_cleanup` — `chunked_manager.prune_stale()` (3600s)
- `orphaned_stage_cleanup` — nicht zuordenbare pending Stages failen (300s, T-063)
- `db_vacuum` — WAL-Checkpoint + VACUUM (86400s = 1x täglich)

### 2. `src/relay_server/core/artifacts.py` — `cleanup_orphaned_artifacts()`
Neue Funktion:
```python
def cleanup_orphaned_artifacts(max_age_days: float = 7.0) -> dict:
    """Lösche Artifakte deren task_id auf keinen existierenden Task mehr verweist
    und die älter als max_age_days sind. Returns {deleted, freed_bytes}."""
```
- SELECT artifacts WHERE task_id IS NOT NULL AND task_id NOT IN (SELECT task_id FROM tasks) AND created_at < now - max_age_days
- Für jeden: Datei löschen + DB-Eintrag löschen
- Log + Event

### 3. `src/relay_server/core/scheduler.py` — `fail_orphaned_stages()`
Neue statische Methode:
```python
@staticmethod
def fail_orphaned_stages() -> dict:
    """Markiere pending Stages als failed, deren Capability von keinem
    online Node heartbeatet wird. Returns {stages_failed, tasks_failed}."""
```
- SELECT pending stages
- Für jede: prüfe ob capability_name in (SELECT capability_name FROM node_capabilities WHERE available=1)
- Wenn nicht: stage → failed, task → failed wenn alle stages terminal
- Events: stage_failed, task_failed

### 4. `src/relay_server/main.py` — Watchdogs durch MaintenanceScheduler ersetzen
- `_heartbeat_watchdog()`, `_claim_ttl_watchdog()`, `_token_cleanup_watchdog()` entfernen
- Stattdessen: `MaintenanceScheduler`-Instanz in `lifespan()` starten
- Ein einziger asyncio-Task: `_maintenance_loop()` der alle 5s `run_due()` aufruft
- In `shutdown()`: `scheduler.run_all()` für graceful shutdown

```python
maintenance = MaintenanceScheduler()

async def _maintenance_loop():
    while True:
        try:
            results = await asyncio.to_thread(maintenance.run_due)
            for name, result in results.items():
                if result:  # non-empty = es wurde was gemacht
                    logger.info("Maintenance [%s]: %s", name, result)
        except Exception as e:
            logger.exception("Maintenance loop error: %s", e)
        await asyncio.sleep(5)
```

### 5. Config — `maintenance`-Sektion in `config.py`
```python
# Maintenance
maintenance_interval_seconds: int = 5
artifact_cleanup_max_age_days: float = 7.0
orphaned_stage_interval_seconds: int = 300
db_vacuum_interval_seconds: int = 86400
```

### 6. Tests

**`tests/test_maintenance.py` — NEU:**
- `test_maintenance_scheduler_register_and_run()` — registrieren + ausführen
- `test_maintenance_scheduler_run_due_only_due()` — nur fällige Tasks laufen
- `test_maintenance_scheduler_status()` — status() zeigt korrekte Infos
- `test_cleanup_orphaned_artifacts()` — Artifact ohne Task wird gelöscht
- `test_cleanup_orphaned_artifacts_keeps_referenced()` — Artifact mit gültigem Task bleibt
- `test_fail_orphaned_stages()` — pending Stage mit unbekannter Capability → failed
- `test_fail_orphaned_stages_keeps_known()` — pending Stage mit bekannter Capability bleibt

**`tests/test_scheduler.py` — ERWEITERN:**
- `test_fail_orphaned_stages()` (Integration)

## Reihenfolge
1. `maintenance.py` — NEU (Kern)
2. `artifacts.py` — `cleanup_orphaned_artifacts()` ergänzen
3. `scheduler.py` — `fail_orphaned_stages()` ergänzen
4. `config.py` — maintenance-Sektion
5. `main.py` — Watchdogs durch MaintenanceScheduler ersetzen
6. Tests
7. `pytest` — alle bestehenden Tests müssen grün bleiben (256 → ~270)
