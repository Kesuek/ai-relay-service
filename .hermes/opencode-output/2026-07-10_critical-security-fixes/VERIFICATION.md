# VERIFICATION.md

## Test-Suite

```bash
cd /home/felix/projects/ai-relay-service
.venv/bin/python -m pytest tests/ -q --ignore=tests/test_zeroconf.py --tb=short 2>&1 | tail -5
```

**Ergebnis (Endzustand nach Task 3):**

```
164 passed, 42 warnings in 115.51s (0:01:55)
```

Nach jedem einzelnen Task wurden die jeweiligen Tests ausgefuehrt:

| Task | Suite | Ergebnis |
|------|-------|----------|
| Task 1 (T-012) | `tests/test_auth.py` | 15 passed in 18.86s |
| Task 2 (T-011) | `tests/test_scheduler.py` | 5 passed in 10.39s |
| Task 3 (T-010) | `tests/test_storage.py` | 12 passed in 13.98s |
| Alle zusammen | `test_auth.py` + `test_scheduler.py` + `test_storage.py` | 32 passed in 43.07s |
| Vollstaendig | `tests/` (ohne `test_zeroconf.py`) | 164 passed in 115.51s |

## Task 1: Fail-fast Pepper-Verifikation

```python
# test_token_pepper_fails_without_session_secret in test_auth.py
# Setzt settings.session_secret = None, resettet _TOKEN_PEPPER,
# erwartet RuntimeError("RELAY_SESSION_SECRET").
```

Der Test bestätigt, dass `_get_token_pepper()` eine `RuntimeError` wirft, wenn
`session_secret` None ist — kein Default-Pepper wird mehr verwendet.

## Task 2: Payload-Limit-Verifikation

```python
# test_task_payload_too_large in test_scheduler.py
# Sendet einen Task mit payload > max_payload_bytes (10 MiB),
# erwartet HTTP 422.
```

Der Test bestätigt, dass Pydantic den Payload validiert und HTTP 422
zurueckgibt, wenn `max_payload_bytes` ueberschritten wird.

## Task 3: Spool-Close-Verifikation

Die bestehenden Storage-Tests (insbesondere `test_storage_large_upload_exceeds_spool_ram_threshold`
mit 2 MiB Upload, der den 1 MiB Spool-RAM-Threshold ueberschreitet) verifizieren,
dass der Spool korrekt auf Platte rollt, der Pfad extrahiert wird, und die Datei
nach `spool.close()` noch erfolgreich verarbeitet wird. Die `finally`-Bereinigung
von `real_path` funktioniert (Datei wird nach Upload geloescht).

## Statische Verifikation der Einzelaenderungen

- **Task 1 (T-012):** `src/relay_server/core/auth.py` — `_get_token_pepper()`
  wirft `RuntimeError` wenn `settings.session_secret` None oder < 32 Zeichen.
  Kein Default-String mehr im Code. Kommentar aktualisiert.
- **Task 2 (T-011):** `src/relay_server/config.py` — neues Setting
  `max_payload_bytes: int = 10 * 1024 * 1024`. `src/relay_server/models/__init__.py`
  und `src/relay_server/models/task.py` — `@model_validator(mode='after')`
  in `StageInput` und `SimpleTaskRequest`, serialisiert Payload via
  `json.dumps()` und vergleicht Laenge gegen `settings.max_payload_bytes`.
- **Task 3 (T-010):** `src/relay_server/api/v2/storage.py` — `spool.close()`
  unmittelbar nach `real_path`-Bestimmung (vor dem `try`-Block).
  `spool.close()` aus `finally` entfernt (wird jetzt nur noch
  `real_path.unlink(missing_ok=True)` ausgefuehrt). `import logging` +
  `logger = logging.getLogger(__name__)` hinzugefuegt. `logger.info()` im
  Fallback-Pfad (Materialisierung des Spools in NamedTemporaryFile).