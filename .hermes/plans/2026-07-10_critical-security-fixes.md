# CRITICAL Security Fixes — Implementation Plan

> **Fuer OpenCode:** Tasks nacheinander abarbeiten. Nach jedem Task: `pytest` laufen lassen, alle Tests muessen gruen bleiben.

**Goal:** Drei CRITICAL-Findings aus dem GitHub-Code-Review beheben: Token Pepper Default, Task Payload unbounded, Chunked Upload Resource Leak.

**Betroffene Dateien:**
- `src/relay_server/core/auth.py`
- `src/relay_server/models/__init__.py`
- `src/relay_server/models/task.py`
- `src/relay_server/config.py`
- `src/relay_server/api/v2/storage.py`
- `tests/test_auth.py`
- `tests/test_scheduler.py`
- `tests/test_storage.py`

---

## Task 1: Token Pepper Default — Fail-Fast statt Default-Secret

**Was das bedeutet:** `_get_token_pepper()` in `auth.py` fallt auf `"relay-default-pepper-change-me"` zurueck, wenn `session_secret` nicht gesetzt ist. Dieser String steht im Sourcecode auf GitHub. Jeder, der den Code kennt, kennt den Pepper. Da `compute_token_lookup()` einen deterministischen HMAC-SHA256 aus Token + Pepper berechnet, koennen Angreifer mit DB-Zugriff Lookup-Hashes vorhersagen. Der Server erzwingt zwar bereits in `main.py` (lifespan) ein `session_secret` >= 32 Zeichen, aber `_get_token_pepper()` umgeht diese Pruefung still — wenn jemand den Code refactored oder die Pruefung entfernt, ist der Default wieder aktiv.

**Objective:** `_get_token_pepper()` soll fail-fast sein: wenn `session_secret` None oder zu kurz ist, eine Exception werfen statt auf einen Default zu fallen.

**Files:**
- Modify: `src/relay_server/core/auth.py` (Zeilen 100-105)
- Test: `tests/test_auth.py`

**Step 1: `_get_token_pepper()` aendern**

In `src/relay_server/core/auth.py`:

```python
def _get_token_pepper() -> str:
    """Return the server-side pepper used for deterministic token lookup."""
    global _TOKEN_PEPPER
    if _TOKEN_PEPPER is None:
        secret = settings.session_secret
        if not secret or len(secret) < 32:
            raise RuntimeError(
                "RELAY_SESSION_SECRET must be set to at least 32 characters "
                "before token operations can use the pepper."
            )
        _TOKEN_PEPPER = secret
    return _TOKEN_PEPPER
```

**Step 2: Test schreiben — Pepper fail-fast ohne session_secret**

In `tests/test_auth.py` einen Test hinzufuegen:

```python
def test_token_pepper_fails_without_session_secret():
    """_get_token_pepper() muss fail-fast wenn session_secret fehlt."""
    from relay_server.core.auth import _get_token_pepper

    # session_secret im Test ist gesetzt (siehe conftest/fixture),
    # also testen wir den Pfad ueber eine temporaere Konfiguration.
    original = settings.session_secret
    try:
        settings.session_secret = None
        # _TOKEN_PEPPER global zuruecksetzen
        import relay_server.core.auth as auth_mod
        auth_mod._TOKEN_PEPPER = None
        with pytest.raises(RuntimeError, match="RELAY_SESSION_SECRET"):
            _get_token_pepper()
    finally:
        settings.session_secret = original
        auth_mod._TOKEN_PEPPER = None
```

**Step 3: Tests laufen**

```bash
cd /home/felix/projects/ai-relay-service
source .venv/bin/activate
.venv/bin/python -m pytest tests/test_auth.py -x -q --tb=short 2>&1 | tail -10
```

Expected: ALL PASSED

**Step 4: Commit**

```bash
git add src/relay_server/core/auth.py tests/test_auth.py
git commit -m "fix(auth): fail-fast in _get_token_pepper instead of weak default pepper"
```

---

## Task 2: Task Payload Size Limit — Input Validation in Pydantic

**Was das bedeutet:** Ein Client kann einen Task mit einem `payload` von mehreren GB JSON erstellen. Der Payload wird als TEXT in SQLite gespeichert (keine Groessenbegrenzung im Schema) und beim Deserialisieren komplett in RAM geladen. Ein boesartiger Node kann den Server mit einem einzigen Request lahmlegen (OOM oder DB-Bloat). Es gibt bereits `max_upload_bytes` (100 MB) fuer Datei-Uploads, aber nichts Vergleichbares fuer Task-Payloads.

**Objective:** Ein `max_payload_bytes`-Setting einfuehren (Default 10 MB) und in den Pydantic-Modellen `StageInput.payload` und `SimpleTaskRequest.payload` validieren.

**Files:**
- Modify: `src/relay_server/config.py` (neues Setting)
- Modify: `src/relay_server/models/__init__.py` (Validation in StageInput, SimpleTaskRequest)
- Modify: `src/relay_server/models/task.py` (gleiche Validation)
- Test: `tests/test_scheduler.py`

**Step 1: `max_payload_bytes` in config.py hinzufuegen**

In `src/relay_server/config.py` nach `max_upload_bytes`:

```python
    # Storage limits
    max_upload_bytes: int = 100 * 1024 * 1024  # 100 MiB
    max_payload_bytes: int = 10 * 1024 * 1024   # 10 MiB — task payload limit
```

**Step 2: Pydantic-Validator in `models/__init__.py`**

In `src/relay_server/models/__init__.py` bei `StageInput` einen `model_validator` hinzufuegen:

```python
import json

from relay_server.config import settings

class StageInput(BaseModel):
    stage_name: str
    capability: str
    depends_on: Optional[List[str]] = None
    timeout_seconds: Optional[int] = None
    payload: Optional[Dict[str, Any]] = None

    @model_validator(mode='after')
    def validate_payload_size(self):
        if self.payload is not None:
            payload_str = json.dumps(self.payload)
            if len(payload_str) > settings.max_payload_bytes:
                raise ValueError(
                    f"Payload exceeds maximum size of {settings.max_payload_bytes} bytes"
                )
        return self
```

Gleichen Validator auch in `SimpleTaskRequest` (Zeile 256-268) einfuegen:

```python
class SimpleTaskRequest(BaseModel):
    capability: str = Field(..., min_length=1)
    payload: Dict[str, Any] = Field(default_factory=dict)
    name: str = ""
    priority: int = Field(default=0, ge=0, le=10)
    timeout_seconds: Optional[int] = None
    owner_node_id: Optional[str] = Field(None, min_length=1)
    idempotency_key: Optional[str] = Field(
        None,
        description="Unique key – prevents duplicates on retries",
    )

    @model_validator(mode='after')
    def validate_payload_size(self):
        payload_str = json.dumps(self.payload)
        if len(payload_str) > settings.max_payload_bytes:
            raise ValueError(
                f"Payload exceeds maximum size of {settings.max_payload_bytes} bytes"
            )
        return self
```

**Step 3: Gleiche Aenderung in `models/task.py`**

In `src/relay_server/models/task.py` bei `StageInput` (Zeile 44-49) und `SimpleTaskRequest` (Zeile 18-30) die gleichen Validatoren einfuegen.

**Wichtig:** `models/task.py` importiert `from relay_server.config import settings` nicht — muss oben hinzugefuegt werden. Achte auf zirkulaere Imports: `models/task.py` importiert `relay_server.models.capability`, aber nicht `relay_server.config`. Das ist safe, weil `config` keine Models importiert.

**Step 4: Test schreiben — Payload zu gross**

In `tests/test_scheduler.py`:

```python
def test_task_payload_too_large():
    """Task mit payload > max_payload_bytes muss 422 zurueckgeben."""
    from relay_server.config import settings

    # Ein Payload, der groesser ist als das Limit
    big_payload = {"data": "x" * (settings.max_payload_bytes + 1)}

    r = client.post(
        "/relay/v2/scheduler/tasks",
        json={
            "task_name": "big-payload-test",
            "stages": [{
                "stage_name": "main",
                "capability": "test.ai",
                "payload": big_payload,
            }],
        },
    )
    assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"
```

**Step 5: Tests laufen**

```bash
cd /home/felix/projects/ai-relay-service
source .venv/bin/activate
.venv/bin/python -m pytest tests/test_scheduler.py -x -q --tb=short 2>&1 | tail -10
```

Expected: ALL PASSED

**Step 6: Commit**

```bash
git add src/relay_server/config.py src/relay_server/models/__init__.py src/relay_server/models/task.py tests/test_scheduler.py
git commit -m "fix(scheduler): add max_payload_bytes validation to prevent OOM/DB-bloat"
```

---

## Task 3: Chunked Upload — SpooledTemporaryFile seek(0) vor Lesen

**Was das bedeutet:** In `storage.py` wird ein `SpooledTemporaryFile` befuellt, dann `spool.seek(0)` aufgerufen (Zeile 72). Danach wird `spool.name` geprueft: wenn es ein gueltiger Pfad ist (weil der Spool auf Platte gespillt wurde), wird der Pfad direkt an `store_artifact_from_file` uebergeben — **ohne den Spool zu schliessen**. Der Spool bleibt offen, bis `finally` (Zeile 105). Bei vielen parallelen Uploads oder einer Exception zwischen Zeile 84 und 105 kann das zu FD-Leaks fuehren. Der Fix: den Spool sofort schliessen, sobald der Pfad extrahiert wurde, und den Pfad danach unabhaengig vom Spool nutzen.

**Objective:** Nachdem `real_path` bestimmt ist, den Spool sofort schliessen statt bis zum `finally`. Zusaetzlich Logging im Fallback-Pfad.

**Files:**
- Modify: `src/relay_server/api/v2/storage.py` (Zeilen 71-105)
- Test: `tests/test_storage.py`

**Step 1: Spool schliessen nach Pfad-Extraktion**

In `src/relay_server/api/v2/storage.py` den Block ab Zeile 71 aendern:

```python
    spool.flush()
    spool.seek(0)

    # SpooledTemporaryFile only exposes a usable .name once it spilled to a
    # real on-disk temp file. Even then the default roll-over may report an
    # integer file descriptor instead of a path, so we only trust string-like
    # names. Whenever there's no usable path (RAM-only upload, or fd-only
    # roll-over), materialise the spooled bytes into a named temp file.
    real_path: Optional[pathlib.Path] = None
    spilled_name = getattr(spool, "name", None)
    if isinstance(spilled_name, (str, bytes, pathlib.PurePath)):
        candidate = pathlib.Path(spilled_name)
        if candidate.exists():
            real_path = candidate
    if real_path is None:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".upload") as out:
            while True:
                buf = spool.read(64 * 1024)
                if not buf:
                    break
                out.write(buf)
        real_path = pathlib.Path(out.name)
        logger.info("Materialised spooled upload to %s (no usable path from SpooledTemporaryFile)", real_path)

    # Close the spool immediately — we have the real_path now.
    spool.close()

    try:
        result = store_artifact_from_file(
            name=file.filename or "unnamed",
            file_path=real_path,
            mime_type=file.content_type,
            task_id=task_id,
            stage_id=stage_id,
            created_by=ctx.node_id,
        )
    finally:
        real_path.unlink(missing_ok=True)
```

**Wichtig:** `logger` muss oben importiert sein. Pruefen ob `import logging` und `logger = logging.getLogger(__name__)` existiert. Falls nicht, hinzufuegen.

**Step 2: Tests laufen**

```bash
cd /home/felix/projects/ai-relay-service
source .venv/bin/activate
.venv/bin/python -m pytest tests/test_storage.py -x -q --tb=short 2>&1 | tail -10
```

Expected: ALL PASSED

**Step 3: Commit**

```bash
git add src/relay_server/api/v2/storage.py
git commit -m "fix(storage): close SpooledTemporaryFile immediately after path extraction, add logging"
```

---

## Abschliessende Antwort fuer das Project Board

Nach erfolgreicher Implementierung:

1. **TASKS.md aktualisieren:**
   - T-010 (Chunked Upload Resource Leak) → `done`
   - T-011 (Task Payload unbounded) → `done`
   - T-012 (Weak Token Pepper Default) → `done`

2. **DECISIONS.md erweitern:**
   - 2026-07-10: CRITICAL-Fixes aus GitHub-Review implementiert
   - max_payload_bytes = 10 MB (configurable via RELAY_MAX_PAYLOAD_BYTES)
   - _get_token_pepper() fail-fast statt Default-Secret
   - SpooledTemporaryFile wird sofort nach Pfad-Extraktion geschlossen

3. **PLAN.md:**
   - Phase 6: T-010, T-011, T-012 als erledigt markieren

## OpenCode-Output

Nach Abarbeitung legt OpenCode sein Ergebnis ab unter:
`.hermes/opencode-output/2026-07-10_critical-security-fixes/`
mit `STATUS.md`, `TASKS.md`, `DECISIONS.md`, `VERIFICATION.md`, `LOG.md`.
