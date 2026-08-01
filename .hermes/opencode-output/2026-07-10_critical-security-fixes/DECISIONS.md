# DECISIONS.md

## 2026-07-10: CRITICAL-Fixes aus GitHub-Review implementiert

**Entscheidung:** Drei CRITICAL-Findings aus dem GitHub-Code-Review behoben:

- **T-012 (Weak Token Pepper Default):** `_get_token_pepper()` in `auth.py`
  wirft jetzt `RuntimeError("RELAY_SESSION_SECRET must be set to at least 32
  characters ...")`, wenn `session_secret` fehlt oder < 32 Zeichen ist, statt
  auf den hartcodierten Default `"relay-default-pepper-change-me"` zu fallen.
  Der Default stand im Sourcecode auf GitHub und war oeffentlich bekannt.
  Mit DB-Zugriff haetten Angreifer Lookup-Hashes vorhersagen koennen.

- **T-011 (Task Payload unbounded):** Neues Setting `max_payload_bytes`
  (Default 10 MiB, configurable via `RELAY_MAX_PAYLOAD_BYTES`).
  Pydantic `@model_validator(mode='after')` in `StageInput` und
  `SimpleTaskRequest` — in beiden `models/__init__.py` und `models/task.py`.
  Serialisiert den Payload zu JSON und vergleicht die Laenge; ueberschreitung
  liefert HTTP 422 (Pydantic-Validation-Error).

- **T-010 (Chunked Upload Resource Leak):** In `storage.py::storage_upload`
  wird `spool.close()` jetzt sofort aufgerufen, sobald `real_path` bestimmt
  ist (nach dem Fallback-Materialisierungs-Pfad). Zuvor blieb der
  `SpooledTemporaryFile` bis zum `finally`-Block offen — bei parallelen Uploads
  oder Exceptions zwischen Pfad-Extraktion und `finally` konnten FDs leaken.
  Der `finally`-Block bereinigt jetzt nur noch `real_path.unlink()`.
  Zusaetzlich wurde `logger.info(...)` im Fallback-Pfad hinzugefuegt.

**Grund:** GitHub-Code-Review identifizierte drei CRITICAL-Findings, die alle
den Datenschutz bzw. die Verfuegbarkeit des Servers gefaehrden: vorhersagbare
Token-Hashes (T-012), OOM/DB-Bloat durch unlimitierte Task-Payloads (T-011),
und FD-Leaks bei gleichzeitigen Uploads (T-010).

**Betroffene Files:** `auth.py`, `config.py`, `models/__init__.py`,
`models/task.py`, `api/v2/storage.py`
**Betroffene Tasks:** T-010, T-011, T-012

---

## Abweichung vom Plan

Siehe `STATUS.md` Abschnitt "Abweichung vom Plan": Die Test-Fixtures in
`test_auth.py`, `test_scheduler.py` und `test_storage.py` wurden um ein
gueltiges `session_secret` (>= 32 Zeichen) und `_TOKEN_PEPPER`-Reset
erweitert, da der neue fail-fast-Pepper aus Task 1 alle Tests betrifft, die
authentifizierte Requests senden.