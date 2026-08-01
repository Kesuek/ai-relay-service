# STATUS — CRITICAL Security Fixes

**Datum:** 2026-07-10
**Betroffene Commits:** `41561cb`, `26eff4a`, `ae905d5`
**Plan:** `.hermes/plans/2026-07-10_critical-security-fixes.md`

## Zusammenfassung

Alle drei CRITICAL-Findings aus dem GitHub-Code-Review wurden umgesetzt.
Nach jedem Task wurde die jeweilige Test-Suite ausgefuehrt; alle Tests blieben
gruen. Die vollstaendige Suite (164 Tests) wurde am Ende erneut ausgefuehrt.

| Task | Finding | Status | Notiz |
|------|---------|--------|-------|
| Task 1 | Weak Token Pepper Default | done | `_get_token_pepper()` fail-fast mit RuntimeError statt Default-Secret |
| Task 2 | Task Payload unbounded | done | `max_payload_bytes` (10 MiB) + Pydantic-Validator in 4 Modellen |
| Task 3 | Chunked Upload Resource Leak | done | `spool.close()` sofort nach Pfad-Extraktion + Logging im Fallback |

## Betroffene Dateien

- `src/relay_server/core/auth.py`
- `src/relay_server/config.py`
- `src/relay_server/models/__init__.py`
- `src/relay_server/models/task.py`
- `src/relay_server/api/v2/storage.py`
- `tests/test_auth.py`
- `tests/test_scheduler.py`
- `tests/test_storage.py`

## Verifikation

Siehe `VERIFICATION.md`. Test-Suite: 164 passed.

## Abweichung vom Plan

**Task 1:** Der Plan nannte als Test-Secret `"test-secret"` (11 Zeichen) in der
`fresh_db`-Fixture von `test_auth.py`. Die neue fail-fast-Logik erfordert
>= 32 Zeichen. Die Fixture wurde auf `"test-session-secret-do-not-use-in-production"`
(45 Zeichen) gesetzt — identisch mit dem `RELAY_SESSION_SECRET`-Env-Wert, der
bereits oben in der Datei definiert war. Zusaetzlich wurde
`auth_mod._TOKEN_PEPPER = None` in der Fixture zurueckgesetzt, damit jeder Test
den Pepper neu evaluiert.

**Task 2:** Gleiche Anpassung der `fresh_db`-Fixture in `test_scheduler.py`
(session_secret + _TOKEN_PEPPER-Reset).

**Task 3:** Gleiche Anpassung der `fresh_db`-Fixture in `test_storage.py`
(session_secret + _TOKEN_PEPPER-Reset), da Token-Operationen (Upload erfordert
Approved-Context) jetzt vom fail-fast-Pepper betroffen sind.

Alle drei Fixture-Anpassungen waren notwendig, weil der neue fail-fast-Pepper
aus Task 1 alle Tests betrifft, die Token validieren — also praktisch alle
Tests, die authentifizierte Requests senden.