# DECISIONS.md

## 2026-07-16: T-001 + T-003 — Artifact Upload + YAML Schema Validation

**Entscheidung:** Zwei Tasks aus dem Project Board umgesetzt:

- **T-001 (Artifact Upload):** Der Worker kann Artifacts nun nativ ueber
  `node-cli artifact upload <file> [--name] [--task-id] [--stage-id]` hochladen,
  ohne curl bemuehen zu muessen. Die `RelayClient`-Klasse erhaelt
  `upload_artifact()`, das die Datei als Multipart-Form-Upload an den bereits
  existierenden Server-Endpunkt `POST /relay/v2/storage/upload` schickt. Bei
  401/403 wird einmalig ein Token-Refresh versucht und der Upload wiederholt
  (analog zu `download_artifact` / `_post_with_retry`). Query-Parameter
  `task_id` und `stage_id` werden optional mitgesendet.
- **T-003 (YAML Schema Validation):** `validate_profile()` validiert die
  capabilities.yaml zunaechst gegen das neu definierte JSON Schema
  `CAPABILITY_SCHEMA` (Draft 2020-12) via `validate_with_schema()`. Das Schema
  prueft Struktur (root ist Mapping mit `capabilities`-Liste), Pflichtfelder
  (`name`), Typen (`version` str, `auto_publish`/`claimable` bool, `handler` str,
  `max_parallel`/`timeout` int) und Ranges (`max_parallel`/`timeout` >= 1) sowie
  unknown keys (`additionalProperties: False`). Die bestehende programmatische
  Validierung bleibt als zweite Schicht fuer komplexe Regeln (z. B. "handler
  required when claimable", "duplicate names").

**Grund:** Worker brauchten bislang curl fuer Artifact-Uploads; der native Client
ist robuster (Token-Refresh, einheitliche Config). Das JSON Schema faengt
strukturelle Profil-Fehler frueher und lesbarer ab, bevor die programmatische
Validierung Details prueft.

**Betroffene Files:** `nodes/common/node_cli.py`, `nodes/common/capability_loader.py`,
`tests/nodes/test_node_cli.py`, `tests/nodes/test_capability_loader.py`
**Betroffene Tasks:** T-001, T-003

---

## Abweichung vom Plan

Siehe `STATUS.md` Abschnitt "Abweichung vom Plan": Die Schema-Validierung greift
vor der programmatischen Validierung, daher wurden 6 bestehende Tests auf die
neuen Schema-Fehlermeldungen umgestellt (gleiche Szenarien). Der im Plan
vorgesehene ungenutzte `import json as json_module` wurde weggelassen.