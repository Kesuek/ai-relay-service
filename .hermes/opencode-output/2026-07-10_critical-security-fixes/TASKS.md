# TASKS.md — CRITICAL Security Fixes

| ID    | Status | Notiz |
|-------|--------|-------|
| T-012 | done | Weak Token Pepper Default: `_get_token_pepper()` fail-fast mit RuntimeError statt `"relay-default-pepper-change-me"` |
| T-011 | done | Task Payload unbounded: `max_payload_bytes` (10 MiB Default) + Pydantic `model_validator` in `StageInput` und `SimpleTaskRequest` (jeweils in `models/__init__.py` und `models/task.py`) |
| T-010 | done | Chunked Upload Resource Leak: `spool.close()` sofort nach `real_path`-Extraktion, `spool.close()` aus `finally` entfernt, Logging im Fallback-Pfad hinzugefuegt |