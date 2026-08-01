# T-001 + T-003: Artifact Upload + YAML Schema Validation — Implementation Plan

> **For OpenCode:** Use `opencode run --agent primary "Abarbeiten von .hermes/plans/2026-07-16_120000-t001-artifact-upload-worker.md" --thinking`

**Goal:** Add `node-cli artifact upload <file>` so workers can upload artifacts to the relay without using curl, and add JSON Schema validation for capabilities.yaml profiles.

**Architecture:** Der Server hat bereits `POST /relay/v2/storage/upload` (multipart, getestet). Der Worker braucht einen nativen Client-Call + CLI-Kommando, analog zum existierenden `download`. Die `RelayClient`-Klasse bekommt `upload_artifact()`, das CLI bekommt `artifact upload <file> [--name] [--task-id] [--stage-id]`. Für T-003 wird ein JSON Schema definiert und in `validate_profile()` gegen die YAML-Struktur geprüft.

**Tech Stack:** Python, httpx, FastAPI (Server-Seite existiert bereits)

---

## Task 1: `RelayClient.upload_artifact()` hinzufügen

**Objective:** Client-Methode, die eine lokale Datei als Multipart-Upload an den Server schickt und die Antwort (artifact_id) zurückgibt.

**Files:**
- Modify: `nodes/common/node_cli.py` (RelayClient-Klasse, nach `download_artifact`)

**Step 1: Methode einfügen**

Füge nach `download_artifact` (Zeile ~351) folgende Methode ein:

```python
    # -- artifact upload -----------------------------------------------------

    def upload_artifact(
        self,
        file_path: Path,
        *,
        name: Optional[str] = None,
        task_id: Optional[str] = None,
        stage_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Upload a local file to the relay as an artifact.

        Returns the server response dict containing ``artifact_id``,
        ``name``, ``size_bytes``, etc. Falls back to a token refresh
        on a 401/403, then retries once.
        """
        url = f"{self.base_url}/relay/v2/storage/upload"
        params: dict[str, str] = {}
        if task_id:
            params["task_id"] = task_id
        if stage_id:
            params["stage_id"] = stage_id

        file_path = Path(file_path)
        upload_name = name or file_path.name

        def _do_upload() -> httpx.Response:
            with file_path.open("rb") as f:
                return httpx.post(
                    url,
                    headers={"Authorization": f"Bearer {self.token}"},
                    files={"file": (upload_name, f, "application/octet-stream")},
                    params=params or None,
                    timeout=self.cfg.get("request_timeout", 30),
                )

        resp = _do_upload()
        if resp.status_code in (401, 403):
            self._refresh_token()
            resp = _do_upload()
        resp.raise_for_status()
        return resp.json()
```

**Step 2: Tests schreiben**

**Files:**
- Modify: `tests/nodes/test_node_cli.py`

Füge nach `test_download_artifact_raises_on_http_error` (ca. Zeile 433) ein:

```python
# artifact upload


def test_upload_artifact_sends_file(isolated_paths: Path, monkeypatch):
    """upload_artifact POSTs the file and returns the server response."""
    base = isolated_paths
    _write(base / "relay_config.json", json.dumps({"base_url": "http://relay:8788", "request_timeout": 10}))
    _write(base / "ai-relay-agent.json", json.dumps({"node_id": "n1", "registration_secret": "rs_abc"}))
    _write(base / "ai-relay-agent.token", "rt_test")

    source = base / "data.txt"
    source.write_text("hello from worker")

    responses: list[dict] = []

    def fake_post(url, **kw):
        responses.append({"url": url, "kw": kw})
        class FakeResp:
            status_code = 200
            def json(self):
                return {"artifact_id": "artifact_uploaded", "name": "data.txt", "size_bytes": 17}
            def raise_for_status(self):
                pass
        return FakeResp()

    monkeypatch.setattr(httpx, "post", fake_post)

    client = cli.RelayClient(
        json.loads((base / "ai-relay-agent.json").read_text()),
        json.loads((base / "relay_config.json").read_text()),
    )
    result = client.upload_artifact(source)

    assert result["artifact_id"] == "artifact_uploaded"
    assert len(responses) == 1
    assert "/relay/v2/storage/upload" in responses[0]["url"]
    # Verify the file was attached as multipart
    files = responses[0]["kw"].get("files", {})
    assert "file" in files


def test_upload_artifact_retries_on_401(isolated_paths: Path, monkeypatch):
    """upload_artifact retries once after a 401."""
    base = isolated_paths
    _write(base / "relay_config.json", json.dumps({"base_url": "http://relay:8788", "request_timeout": 10}))
    _write(base / "ai-relay-agent.json", json.dumps({"node_id": "n1", "registration_secret": "rs_abc"}))
    _write(base / "ai-relay-agent.token", "rt_test")

    source = base / "data.txt"
    source.write_text("data")

    call_count = 0

    def fake_post(url, **kw):
        nonlocal call_count
        call_count += 1
        class FakeResp:
            status_code = 200 if call_count > 1 else 401
            def json(self):
                return {"artifact_id": "artifact_retried", "name": "data.txt", "size_bytes": 4}
            def raise_for_status(self):
                if self.status_code >= 400:
                    raise httpx.HTTPStatusError("auth", request=None, response=self)
        return FakeResp()

    monkeypatch.setattr(httpx, "post", fake_post)
    # Mock refresh to succeed
    monkeypatch.setattr(cli.RelayClient, "_refresh_token", lambda self: True)

    client = cli.RelayClient(
        json.loads((base / "ai-relay-agent.json").read_text()),
        json.loads((base / "relay_config.json").read_text()),
    )
    result = client.upload_artifact(source)
    assert result["artifact_id"] == "artifact_retried"
    assert call_count == 2


def test_upload_artifact_passes_task_and_stage_params(isolated_paths: Path, monkeypatch):
    """upload_artifact forwards task_id and stage_id as query params."""
    base = isolated_paths
    _write(base / "relay_config.json", json.dumps({"base_url": "http://relay:8788", "request_timeout": 10}))
    _write(base / "ai-relay-agent.json", json.dumps({"node_id": "n1", "registration_secret": "rs_abc"}))
    _write(base / "ai-relay-agent.token", "rt_test")

    source = base / "data.txt"
    source.write_text("data")
    captured: dict = {}

    def fake_post(url, **kw):
        captured["url"] = url
        captured["params"] = kw.get("params")
        class FakeResp:
            status_code = 200
            def json(self):
                return {"artifact_id": "a1"}
            def raise_for_status(self):
                pass
        return FakeResp()

    monkeypatch.setattr(httpx, "post", fake_post)

    client = cli.RelayClient(
        json.loads((base / "ai-relay-agent.json").read_text()),
        json.loads((base / "relay_config.json").read_text()),
    )
    client.upload_artifact(source, task_id="task_99", stage_id="stage_88")
    assert "task_id=task_99" in captured["url"] or captured["params"] == {"task_id": "task_99", "stage_id": "stage_88"}
```

**Step 3: Tests laufen lassen**

```bash
cd /home/felix/projects/ai-relay-service
.venv/bin/python -m pytest tests/nodes/test_node_cli.py::test_upload_artifact_sends_file tests/nodes/test_node_cli.py::test_upload_artifact_retries_on_401 tests/nodes/test_node_cli.py::test_upload_artifact_passes_task_and_stage_params -v
```

Expected: 3 passed

**Step 4: Commit**

```bash
git add nodes/common/node_cli.py tests/nodes/test_node_cli.py
git commit -m "feat(node-cli): add RelayClient.upload_artifact()"
```

---

## Task 2: `node-cli artifact upload` CLI-Kommando

**Objective:** CLI-Befehl `node-cli artifact upload <file>` der `RelayClient.upload_artifact()` aufruft.

**Files:**
- Modify: `nodes/common/node_cli.py` (Parser + Command-Handler)

**Step 1: Handler-Funktion einfügen**

Füge nach `_cmd_artifact_download` (ca. Zeile 773) ein:

```python
def _cmd_artifact_upload(args: argparse.Namespace) -> int:
    _setup_logging(args.log_level)
    meta = load_meta()
    cfg = _effective_config()
    client = RelayClient(meta, cfg)
    file_path = Path(args.file)
    if not file_path.exists():
        print(f"file not found: {file_path}", file=sys.stderr)
        return 2
    result = client.upload_artifact(
        file_path,
        name=args.name,
        task_id=args.task_id,
        stage_id=args.stage_id,
    )
    print(json.dumps(result, indent=2, default=str))
    return 0
```

**Step 2: Parser-Eintrag hinzufügen**

Füge nach dem `artifact download`-Parser-Block (ca. Zeile 1028) ein:

```python
    p_artifact_upload = p_artifact_sub.add_parser(
        "upload", help="Upload a local file as an artifact to the relay."
    )
    p_artifact_upload.add_argument("file", type=str, help="Path to the file to upload.")
    p_artifact_upload.add_argument(
        "--name", default=None, help="Artifact name (default: filename)."
    )
    p_artifact_upload.add_argument(
        "--task-id", default=None, help="Optional task ID to associate with."
    )
    p_artifact_upload.add_argument(
        "--stage-id", default=None, help="Optional stage ID to associate with."
    )
    p_artifact_upload.set_defaults(func=_cmd_artifact_upload)
```

**Step 3: Test für CLI-Kommando schreiben**

Füge nach `test_cmd_artifact_download_invokes_client` (ca. Zeile 460) ein:

```python
def test_cmd_artifact_upload_invokes_client(isolated_paths: Path, monkeypatch, capsys):
    """node-cli artifact upload calls RelayClient.upload_artifact()."""
    base = isolated_paths
    _write(base / "relay_config.json", json.dumps({"base_url": "http://relay:8788", "request_timeout": 10}))
    _write(base / "ai-relay-agent.json", json.dumps({"node_id": "n1", "registration_secret": "rs_abc"}))
    _write(base / "ai-relay-agent.token", "rt_test")

    source = base / "upload-me.txt"
    source.write_text("payload")

    captured: dict = {}

    def fake_upload(file_path, *, name=None, task_id=None, stage_id=None):
        captured["file_path"] = str(file_path)
        captured["name"] = name
        captured["task_id"] = task_id
        captured["stage_id"] = stage_id
        return {"artifact_id": "a_cli", "name": name or Path(file_path).name, "size_bytes": 7}

    monkeypatch.setattr(cli.RelayClient, "upload_artifact", staticmethod(fake_upload))

    rc = cli.main(["artifact", "upload", str(source), "--name", "cli-upload.bin"])
    assert rc == 0
    assert captured["file_path"] == str(source)
    assert captured["name"] == "cli-upload.bin"

    out = capsys.readouterr().out
    assert "a_cli" in out


def test_cmd_artifact_upload_missing_file(isolated_paths: Path, monkeypatch, capsys):
    """node-cli artifact upload exits with code 2 when file is missing."""
    base = isolated_paths
    _write(base / "relay_config.json", json.dumps({"base_url": "http://relay:8788", "request_timeout": 10}))
    _write(base / "ai-relay-agent.json", json.dumps({"node_id": "n1", "registration_secret": "rs_abc"}))
    _write(base / "ai-relay-agent.token", "rt_test")

    rc = cli.main(["artifact", "upload", "/nonexistent/file.bin"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "not found" in err
```

**Step 4: Tests laufen lassen**

```bash
cd /home/felix/projects/ai-relay-service
.venv/bin/python -m pytest tests/nodes/test_node_cli.py::test_cmd_artifact_upload_invokes_client tests/nodes/test_node_cli.py::test_cmd_artifact_upload_missing_file -v
```

Expected: 2 passed

**Step 5: Alle Tests laufen lassen**

```bash
cd /home/felix/projects/ai-relay-service
.venv/bin/python -m pytest tests/nodes/test_node_cli.py -v
```

Expected: alle Tests grün (vorher 483 lines, ~20 tests)

**Step 6: Commit**

```bash
git add nodes/common/node_cli.py tests/nodes/test_node_cli.py
git commit -m "feat(node-cli): add artifact upload CLI command"
```

---

## Task 3: Dokumentation aktualisieren

**Objective:** Die `node-cli`-Hilfe und ggf. die READMEs erwähnen das neue Kommando.

**Files:**
- Modify: `nodes/common/node_cli.py` (Docstring — die Usage-Zeile oben)
- Modify: `nodes/common/README.md` (falls vorhanden, Tabelle ergänzen)

**Step 1: Docstring aktualisieren**

In der Datei `nodes/common/node_cli.py` die Usage-Zeile im Modul-Docstring (Zeile 15) ergänzen:

```diff
-        node-cli artifact download <artifact_id> [--output <path>]
+        node-cli artifact download <artifact_id> [--output <path>]
+        node-cli artifact upload <file> [--name <name>] [--task-id <id>] [--stage-id <id>]
```

**Step 2: README prüfen und ggf. ergänzen**

```bash
cd /home/felix/projects/ai-relay-service
grep -n "artifact" nodes/common/README.md
```

Falls eine Tabelle existiert, `artifact upload` als Zeile ergänzen.

**Step 3: Commit**

```bash
git add nodes/common/node_cli.py nodes/common/README.md
git commit -m "docs(node-cli): document artifact upload command"
```

---

## Task 4: JSON Schema für capabilities.yaml definieren

**Objective:** Ein JSON Schema (Draft 2020-12) für capabilities.yaml erstellen, das die Struktur formal beschreibt. Das Schema wird als Python-Dict in `capability_loader.py` definiert und in `validate_profile()` als zusätzliche Prüfung vor der bestehenden programmatischen Validierung ausgeführt.

**What this means:** Bisher wird die YAML nur programmatisch validiert — Felder werden einzeln auf Typ und Wertebereich geprüft. Ein JSON Schema fängt strukturelle Fehler früher und lesbarer: unbekannte Felder, falsche Typen, fehlende Pflichtfelder. Die programmatische Validierung bleibt als zweite Schicht für komplexe Regeln (z.B. "handler required when claimable").

**Files:**
- Modify: `nodes/common/capability_loader.py` (Schema-Definition + Integration in validate_profile)
- Modify: `tests/nodes/test_capability_loader.py` (Tests für Schema-Fehler)

**Step 1: Schema definieren**

Füge in `capability_loader.py` nach den Imports (ca. Zeile 40) ein:

```python
# ---------------------------------------------------------------------------
# JSON Schema for capability profiles (Draft 2020-12)
# ---------------------------------------------------------------------------

CAPABILITY_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["capabilities"],
    "properties": {
        "capabilities": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "version": {"type": "string", "minLength": 1},
                    "auto_publish": {"type": "boolean"},
                    "claimable": {"type": "boolean"},
                    "handler": {"type": "string"},
                    "max_parallel": {"type": "integer", "minimum": 1},
                    "timeout": {"type": "integer", "minimum": 1},
                },
                "additionalProperties": False,
            },
        }
    },
    "additionalProperties": False,
}
```

**Step 2: Schema-Validator-Funktion einfügen**

Füge nach der Schema-Definition ein:

```python
import json as json_module


def validate_with_schema(data: dict[str, Any]) -> list[str]:
    """Validate parsed YAML data against CAPABILITY_SCHEMA.

    Returns a list of human-readable error messages. An empty list means
    the data is structurally valid. Uses ``jsonschema`` if available,
    otherwise falls back to a basic structural check.
    """
    errors: list[str] = []

    # Basic structural check (works without jsonschema dependency).
    if not isinstance(data, dict):
        errors.append("profile root must be a mapping")
        return errors
    if "capabilities" not in data:
        errors.append("'capabilities' key is required")
        return errors
    if not isinstance(data["capabilities"], list):
        errors.append("'capabilities' must be a list")
        return errors

    for i, entry in enumerate(data["capabilities"]):
        prefix = f"capabilities[{i}]"
        if not isinstance(entry, dict):
            errors.append(f"{prefix}: must be a mapping, got {type(entry).__name__}")
            continue
        if "name" not in entry or not isinstance(entry.get("name"), str) or not entry["name"].strip():
            errors.append(f"{prefix}: 'name' is required and must be a non-empty string")
        # Check for unknown keys
        allowed = {"name", "version", "auto_publish", "claimable", "handler", "max_parallel", "timeout"}
        extra = set(entry.keys()) - allowed
        if extra:
            errors.append(f"{prefix}: unknown keys: {', '.join(sorted(extra))}")
        # Type checks for optional fields
        for key, expected_type in [
            ("version", str),
            ("auto_publish", bool),
            ("claimable", bool),
            ("handler", str),
            ("max_parallel", int),
            ("timeout", int),
        ]:
            val = entry.get(key)
            if val is not None and not isinstance(val, expected_type):
                errors.append(f"{prefix}.{key}: expected {expected_type.__name__}, got {type(val).__name__}")
        # Range checks
        for key in ("max_parallel", "timeout"):
            val = entry.get(key)
            if isinstance(val, int) and val < 1:
                errors.append(f"{prefix}.{key}: must be >= 1, got {val}")

    return errors
```

**Step 3: In `validate_profile()` integrieren**

Ersetze den Anfang von `validate_profile()` (ca. Zeile 282) um die Schema-Prüfung vor der programmatischen Validierung:

```python
def validate_profile(
    source: str | os.PathLike[str] | dict[str, Any] | Path,
) -> list[dict[str, Any]]:
    """Validate a profile and return the normalized capabilities list.

    Accepts either a path to a YAML file or an already-parsed dict.
    Raises :class:`CapabilityValidationError` on any problem.
    """
    if isinstance(source, dict):
        # Schema validation first
        schema_errors = validate_with_schema(source)
        if schema_errors:
            raise CapabilityValidationError(
                "schema validation failed:\n  " + "\n  ".join(schema_errors)
            )
        if "capabilities" not in source:
            raise CapabilityValidationError("'capabilities' key missing")
        return _normalize_caps_list(source["capabilities"], file=None)

    path = Path(source)
    file_label = str(path)
    if not path.exists():
        raise CapabilityValidationError(f"profile file not found: {file_label}")
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CapabilityValidationError(f"cannot read profile {file_label}: {exc}") from exc
    try:
        parsed = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        line = getattr(exc, "problem_mark", None)
        line_no = line.line + 1 if line is not None else None
        raise CapabilityValidationError(
            f"YAML syntax error: {exc}",
            file=file_label,
            line=line_no,
        ) from exc

    if parsed is None:
        parsed = {}
    if not isinstance(parsed, dict):
        raise CapabilityValidationError(
            "profile root must be a mapping with a 'capabilities' key",
            file=file_label,
        )

    # Schema validation
    schema_errors = validate_with_schema(parsed)
    if schema_errors:
        raise CapabilityValidationError(
            "schema validation failed:\n  " + "\n  ".join(schema_errors),
            file=file_label,
        )

    if "capabilities" not in parsed:
        raise CapabilityValidationError(
            "'capabilities' key missing or not a list",
            file=file_label,
        )
    return _normalize_caps_list(parsed["capabilities"], file=file_label)
```

**Step 4: Tests für Schema-Validierung schreiben**

Füge in `tests/nodes/test_capability_loader.py` nach den bestehenden validate-Tests (ca. Zeile 169) ein:

```python
# ---------------------------------------------------------------------------
# JSON Schema validation
# ---------------------------------------------------------------------------


def test_schema_rejects_unknown_keys():
    """Schema catches unknown keys in capability entries."""
    with pytest.raises(CapabilityValidationError, match="unknown keys"):
        validate_profile({"capabilities": [{"name": "x", "unknown_field": "bad"}]})


def test_schema_rejects_wrong_type_for_version():
    """Schema catches type errors in optional fields."""
    with pytest.raises(CapabilityValidationError, match="version.*str"):
        validate_profile({"capabilities": [{"name": "x", "version": 123}]})


def test_schema_rejects_negative_max_parallel():
    """Schema catches range violations."""
    with pytest.raises(CapabilityValidationError, match="max_parallel.*>= 1"):
        validate_profile({"capabilities": [{"name": "x", "max_parallel": 0}]})


def test_schema_rejects_negative_timeout():
    with pytest.raises(CapabilityValidationError, match="timeout.*>= 1"):
        validate_profile({"capabilities": [{"name": "x", "timeout": -1}]})


def test_schema_rejects_capabilities_not_a_list():
    with pytest.raises(CapabilityValidationError, match="capabilities.*must be a list"):
        validate_profile({"capabilities": "not-a-list"})


def test_schema_rejects_entry_not_a_mapping():
    with pytest.raises(CapabilityValidationError, match="must be a mapping"):
        validate_profile({"capabilities": ["string-entry"]})


def test_schema_rejects_missing_name():
    with pytest.raises(CapabilityValidationError, match="name.*required"):
        validate_profile({"capabilities": [{"version": "1.0.0"}]})


def test_schema_rejects_empty_name():
    with pytest.raises(CapabilityValidationError, match="name.*required"):
        validate_profile({"capabilities": [{"name": ""}]})


def test_schema_passes_valid_profile():
    """A valid profile passes schema validation without errors."""
    caps = validate_profile({
        "capabilities": [
            {"name": "chat.ai", "version": "1.0.0", "auto_publish": True,
             "claimable": True, "handler": "/bin/true", "max_parallel": 2, "timeout": 300},
        ]
    })
    assert len(caps) == 1
    assert caps[0]["name"] == "chat.ai"
```

**Step 5: Tests laufen lassen**

```bash
cd /home/felix/projects/ai-relay-service
.venv/bin/python -m pytest tests/nodes/test_capability_loader.py -v
```

Expected: alle Tests grün (vorher ~30 tests, jetzt ~40)

**Step 6: Commit**

```bash
git add nodes/common/capability_loader.py tests/nodes/test_capability_loader.py
git commit -m "feat(capability-loader): add JSON Schema validation for capabilities.yaml"
```

---

## Abschliessende Antwort fuer das Project Board

Nach erfolgreicher Implementierung:

1. **TASKS.md:** T-001 und T-003 auf `✅ done` setzen
2. **DECISIONS.md:** Eintrag hinzufügen — "T-001 umgesetzt: `node-cli artifact upload` + `RelayClient.upload_artifact()`; T-003 umgesetzt: JSON Schema für capabilities.yaml"
3. **PLAN.md:** Phase 6 — `Artifact upload/download from worker side` und `YAML schema validation for capabilities.yaml` auf `[x]` setzen
4. **IDEAS.md:** Ggf. nichts — waren klare Tasks

## OpenCode-Output

OpenCode legt sein Ergebnis ab unter:
```
.hermes/opencode-output/2026-07-16_120000-t001-artifact-upload-worker/
├── STATUS.md
├── TASKS.md
├── DECISIONS.md
├── VERIFICATION.md
└── LOG.md
```
