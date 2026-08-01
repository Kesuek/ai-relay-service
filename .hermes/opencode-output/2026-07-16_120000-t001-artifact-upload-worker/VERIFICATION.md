# VERIFICATION.md

## Test-Suite (betroffene Module)

```bash
cd /home/felix/projects/ai-relay-service
.venv/bin/python -m pytest tests/nodes/test_node_cli.py tests/nodes/test_capability_loader.py -v 2>&1 | tail -5
```

**Ergebnis (Endzustand nach Task 4):**

```
70 passed, 6 warnings in 0.15s
```

Nach jedem einzelnen Task wurde die jeweilige Suite ausgefuehrt und blieb gruen:

| Task | Suite | Ergebnis |
|------|-------|----------|
| Task 1 | `test_node_cli.py::test_upload_artifact_*` (3 Tests) | 3 passed |
| Task 2 | `test_node_cli.py` (komplett) | 32 passed |
| Task 4 | `test_capability_loader.py` (komplett) | 38 passed |

## Task 1: upload_artifact — Einzelnachweis

```bash
.venv/bin/python -m pytest tests/nodes/test_node_cli.py::test_upload_artifact_sends_file \
  tests/nodes/test_node_cli.py::test_upload_artifact_retries_on_401 \
  tests/nodes/test_node_cli.py::test_upload_artifact_passes_task_and_stage_params -v
```

```
3 passed
```

- `test_upload_artifact_sends_file`: POST geht an `/relay/v2/storage/upload`,
  Datei wird als multipart `file`-Feld angehaengt, Server-Antwort wird zurueckgegeben.
- `test_upload_artifact_retries_on_401`: erster POST -> 401, Token-Refresh-Mock,
  zweiter POST -> 200; `call_count == 2`, Ergebnis `artifact_retried`.
- `test_upload_artifact_passes_task_and_stage_params`: `task_id`/`stage_id`
  werden als Query-Parameter weitergereicht.

## Task 2: CLI-Kommando — Einzelnachweis

```bash
.venv/bin/python -m pytest tests/nodes/test_node_cli.py::test_cmd_artifact_upload_invokes_client \
  tests/nodes/test_node_cli.py::test_cmd_artifact_upload_missing_file -v
```

```
2 passed
```

- `test_cmd_artifact_upload_invokes_client`: `node-cli artifact upload <file>
  --name ...` ruft `RelayClient.upload_artifact()` mit korrekten Argumenten auf,
  Exit-Code 0, JSON-Antwort wird ausgegeben.
- `test_cmd_artifact_upload_missing_file`: nicht existierende Datei -> Exit-Code 2
  und "not found" auf stderr.

Parser-Verfuegbarkeit (implizit ueber `test_help_shows_all_subcommands`, der
`artifact` unter den erwarteten Subcommands enthaelt):

```bash
.venv/bin/python -c "
from nodes.common import node_cli as cli
p = cli.build_parser()
ns = p.parse_args(['artifact','upload','/tmp/x','--name','n','--task-id','t','--stage-id','s'])
assert ns.func.__name__ == '_cmd_artifact_upload'
assert ns.file == '/tmp/x' and ns.name == 'n' and ns.task_id == 't' and ns.stage_id == 's'
print('PARSER OK')
"
```

## Task 4: JSON Schema — Einzelnachweis

```bash
.venv/bin/python -m pytest tests/nodes/test_capability_loader.py -k schema -v
```

```
9 passed
```

- `test_schema_rejects_unknown_keys`: unknown keys werden gemeldet.
- `test_schema_rejects_wrong_type_for_version`: Typfehler in optionalen Feldern.
- `test_schema_rejects_negative_max_parallel` / `test_schema_rejects_negative_timeout`:
  Range-Verletzungen (`< 1`).
- `test_schema_rejects_capabilities_not_a_list`: `capabilities` muss Liste sein.
- `test_schema_rejects_entry_not_a_mapping`: Eintraege muessen Mappings sein.
- `test_schema_rejects_missing_name` / `test_schema_rejects_empty_name`: `name`
  Pflichtfeld, nicht-leer.
- `test_schema_passes_valid_profile`: gueltiges Profil mit allen Feldern
  passiert Schema + Normalisierung.

## Statische Verifikation der Einzelaenderungen

- **Task 1:** `nodes/common/node_cli.py` — neue Methode
  `RelayClient.upload_artifact(file_path, *, name, task_id, stage_id)`. Baut
  Multipart-Upload (`files={"file": (upload_name, f, "application/octet-stream")}`),
  setzt Bearer-Header, 401/403 -> `_refresh_token()` + einmaliger Retry,
  `resp.raise_for_status()`, Rueckgabe `resp.json()`.
- **Task 2:** `nodes/common/node_cli.py` — `_cmd_artifact_upload()` prueft
  Dateiexistenz (Exit 2 bei Fehlen), ruft `upload_artifact()`, gibt JSON aus.
  Parser-Eintrag `p_artifact_sub.add_parser("upload", ...)` mit `file`,
  `--name`, `--task-id`, `--stage-id`.
- **Task 3:** `nodes/common/node_cli.py` Modul-Docstring enthaelt jetzt die
  `artifact upload`-Usage-Zeile. README enthaelt keine CLI-Befehlstabelle und
  wurde daher (wie im Plan vorgesehen) nicht geaendert.
- **Task 4:** `nodes/common/capability_loader.py` — `CAPABILITY_SCHEMA` (Draft
  2020-12) + `validate_with_schema()` (basic structural check, ohne
  jsonschema-Dependency). `validate_profile()` ruft `validate_with_schema()`
  fuer beide Eingabeformen (dict + Dateipfad) vor der bestehenden Pruefung auf
  und wirft `CapabilityValidationError("schema validation failed: ...")`.