# LOG.md — Abarbeitung T-001 + T-003 (Artifact Upload + YAML Schema Validation)

**Start:** 2026-07-16
**Plan:** `.hermes/plans/2026-07-16_120000-t001-artifact-upload-worker.md`

## Ablauf

1. **Kontext-Check:** Vor der ersten Aenderung wurden die im Plan genannten
   Code-Stellen gelesen und gegen den tatsaechlichen Stand abgeglichen:
   `RelayClient.__init__` (token via `load_token()`, `base_url`, `cfg`),
   `_refresh_token()`/`_post_with_retry` als Vorbild fuer den 401/403-Retry,
   `download_artifact()` als Positionsmarker, `_cmd_artifact_download` +
   Parser-Block `p_artifact_download` als Vorlagen, `validate_profile()` in
   `capability_loader.py`, `CapabilityValidationError`-Signatur (`file=`,
   `line=`), Imports. Alle Stellen stimmten mit dem Plan ueberein.

2. **Task 1 (`RelayClient.upload_artifact`):** Methode nach `download_artifact`
   eingefuegt (multipart `files`-Feld, Bearer-Header, `params` fuer task_id/
   stage_id, 401/403-Retry via `_refresh_token`). 3 Tests in
   `tests/nodes/test_node_cli.py` ergaenzt. pytest (3 Tests): 3 passed.
   Commit `e3910c4`.

3. **Task 2 (CLI-Kommando):** `_cmd_artifact_upload()` nach
   `_cmd_artifact_download` eingefuegt (Dateiexistenz-Check -> Exit 2,
   `upload_artifact()`-Aufruf, JSON-Ausgabe). Parser-Eintrag
   `p_artifact_sub.add_parser("upload", ...)` mit `file`/`--name`/`--task-id`/
   `--stage-id`. 2 CLI-Tests ergaenzt. pytest (2 Tests): 2 passed. Komplette
   `test_node_cli.py`: 32 passed. Commit `4b867e6`.

4. **Task 3 (Doku):** Modul-Docstring in `node_cli.py` um die
   `node-cli artifact upload <file> ...`-Usage-Zeile ergaenzt.
   `nodes/common/README.md` enthaelt keine CLI-Befehlstabelle (dokumentiert den
   Poller-Bootstrap, keine Subcommand-Tabelle) und wurde daher nicht
   geaendert — wie im Plan ("Falls eine Tabelle existiert, ergaenzen")
   vorgesehen. Commit `bca36cc`.

5. **Task 4 (JSON Schema):** Vier Teilschritte:
   - 4.1 `CAPABILITY_SCHEMA` (Draft 2020-12) nach den Imports in
     `capability_loader.py` definiert.
   - 4.2 `validate_with_schema()` mit basic structural check (ohne
     jsonschema-Dependency) eingefuegt.
   - 4.3 `validate_profile()` fuer *beide* Eingabeformen (dict + Dateipfad)
     um Schema-Pruefung *vor* der bestehenden Pruefung ergaenzt.
   - 4.4 9 neue Schema-Tests in `tests/nodes/test_capability_loader.py`.
   - 4.5 **Abweichung:** Die Schema-Pruefung greift vor der programmatischen
     Validierung, daher schlagen 6 bestehende Tests fehl (andere
     Fehlermeldungen). Diese 6 Tests wurden auf die neuen Schema-Meldungen
     umgestellt (gleiche Szenarien, neue Message-Regexes). pytest
     (komplett): 38 passed. Commit `5dbc2c3`.

## Endzustand

70 passed (32 `test_node_cli.py` + 38 `test_capability_loader.py`), 6 warnings.
Kein Regressions- oder neu eingefuehrter Testfehler.

## Commits

- `e3910c4` feat(node-cli): add RelayClient.upload_artifact()
- `4b867e6` feat(node-cli): add artifact upload CLI command
- `bca36cc` docs(node-cli): document artifact upload command
- `5dbc2c3` feat(capability-loader): add JSON Schema validation for capabilities.yaml

## Output

- `STATUS.md`
- `TASKS.md`
- `DECISIONS.md`
- `VERIFICATION.md`
- `LOG.md` (diese Datei)