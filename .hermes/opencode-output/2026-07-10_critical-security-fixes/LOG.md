# LOG.md — Abarbeitung CRITICAL Security Fixes

**Start:** 2026-07-10
**Plan:** `.hermes/plans/2026-07-10_critical-security-fixes.md`

## Ablauf

1. **Kontext-Check:** Vor der ersten Aenderung wurden alle im Plan genannten
   Code-Stellen gelesen und gegen den tatsaechlichen Stand abgeglichen:
   - `auth.py` Zeilen 100-105 (`_get_token_pepper` mit Default-Pepper)
   - `config.py` Zeile 41 (`max_upload_bytes`, kein `max_payload_bytes`)
   - `models/__init__.py` (StageInput Zeile 126, SimpleTaskRequest Zeile 256)
   - `models/task.py` (StageInput Zeile 44, SimpleTaskRequest Zeile 18)
   - `api/v2/storage.py` Zeilen 71-105 (Spool-Handling mit `spool.close()`
     im `finally`)
   - `tests/test_auth.py`, `tests/test_scheduler.py`, `tests/test_storage.py`
   Alle Stellen stimmten mit dem Plan ueberein.

2. **Task 1 (T-012, Weak Token Pepper Default):**
   - `_get_token_pepper()` in `auth.py` auf fail-fast umgebaut: `RuntimeError`
     wenn `session_secret` None oder < 32 Zeichen.
   - Kommentar ueber `_TOKEN_PEPPER` aktualisiert.
   - Test `test_token_pepper_fails_without_session_secret` in `test_auth.py`
     hinzugefuegt.
   - **Abweichung:** `fresh_db`-Fixture in `test_auth.py` hatte
     `session_secret = "test-secret"` (11 Zeichen) — zu kurz fuer neue
     Pruefung. Auf `"test-session-secret-do-not-use-in-production"` (45 Zeichen)
     gesetzt. `_TOKEN_PEPPER`-Reset in Fixture hinzugefuegt.
   - pytest: 15 passed.

3. **Task 2 (T-011, Task Payload unbounded):**
   - `max_payload_bytes: int = 10 * 1024 * 1024` in `config.py` hinzugefuegt.
   - `import json` + `from relay_server.config import settings` in
     `models/__init__.py` hinzugefuegt. `@model_validator(mode='after')` in
     `StageInput` und `SimpleTaskRequest` eingefuegt.
   - Gleiche Aenderungen in `models/task.py` (zusaetzlich `model_validator`
     Import).
   - Test `test_task_payload_too_large` in `test_scheduler.py` hinzugefuegt.
   - **Anpassung:** `fresh_db`-Fixture in `test_scheduler.py` um
     `session_secret` + `_TOKEN_PEPPER`-Reset erweitert (gleicher Grund wie
     Task 1). `RELAY_SESSION_SECRET`-Env oben hinzugefuegt.
   - Kein zirkularer Import: `config.py` importiert keine Models.
   - pytest: 5 passed.

4. **Task 3 (T-010, Chunked Upload Resource Leak):**
   - `import logging` + `logger = logging.getLogger(__name__)` in
     `storage.py` hinzugefuegt.
   - `spool.close()` unmittelbar nach `real_path`-Bestimmung verschoben
     (vor dem `try`-Block). `spool.close()` aus `finally` entfernt.
   - `logger.info(...)` im Fallback-Pfad (Materialisierung) hinzugefuegt.
   - **Anpassung:** `fresh_db`-Fixture in `test_storage.py` um
     `session_secret` + `_TOKEN_PEPPER`-Reset erweitert, da Upload-Endpoint
     `get_approved_context` nutzt (Token-Validierung -> Pepper).
   - pytest: 12 passed.

5. **Endverifikation:** Vollstaendige Suite:
   ```
   164 passed, 42 warnings in 115.51s
   ```

## Endzustand

164 passed, 42 warnings. Kein Regressions- oder neu eingefuehrter Testfehler.
Drei Commits, einer pro Task.

## Commits

```
ae905d5 fix(storage): close SpooledTemporaryFile immediately after path extraction, add logging
26eff4a fix(scheduler): add max_payload_bytes validation to prevent OOM/DB-bloat
41561cb fix(auth): fail-fast in _get_token_pepper instead of weak default pepper
```

## Output

- `STATUS.md`
- `TASKS.md`
- `DECISIONS.md`
- `VERIFICATION.md`
- `LOG.md` (diese Datei)