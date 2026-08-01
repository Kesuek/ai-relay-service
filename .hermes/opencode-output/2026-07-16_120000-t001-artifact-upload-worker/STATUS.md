# STATUS — T-001 + T-003: Artifact Upload + YAML Schema Validation

**Datum:** 2026-07-16
**Betroffene Commits:** `e3910c4`, `4b867e6`, `bca36cc`, `5dbc2c3`
**Plan:** `.hermes/plans/2026-07-16_120000-t001-artifact-upload-worker.md`

## Zusammenfassung

Beide Tasks wurden vollstaendig umgesetzt. `node-cli artifact upload` erlaubt Workern,
Artifacts ohne curl direkt an den Relay hochzuladen; die `RelayClient`-Klasse erhaelt
die native `upload_artifact()`-Methode. Zusaetzlich validiert `validate_profile()` die
capabilities.yaml-Struktur gegen ein JSON Schema (Draft 2020-12), bevor die
programmatische Validierung laeuft.

| Task | Inhalt | Status | Commit |
|------|--------|--------|--------|
| Task 1 | `RelayClient.upload_artifact()` + 3 Tests | ✅ done | `e3910c4` |
| Task 2 | `node-cli artifact upload` CLI-Kommando + 2 Tests | ✅ done | `4b867e6` |
| Task 3 | Docstring um `artifact upload` ergaenzt | ✅ done | `bca36cc` |
| Task 4 | JSON Schema fuer capabilities.yaml + 9 Tests | ✅ done | `5dbc2c3` |

## Betroffene Dateien

- `nodes/common/node_cli.py` — `RelayClient.upload_artifact()`, `_cmd_artifact_upload`,
  Parser-Eintrag, Modul-Docstring
- `nodes/common/capability_loader.py` — `CAPABILITY_SCHEMA`, `validate_with_schema()`,
  Integration in `validate_profile()`
- `tests/nodes/test_node_cli.py` — 5 neue Tests
- `tests/nodes/test_capability_loader.py` — 9 neue Tests + 6 bestehende Tests an
  Schema-Fehlermeldungen angepasst

## Verifikation

Siehe `VERIFICATION.md`. Betroffene Suiten: 70 passed
(`test_node_cli.py` 32 + `test_capability_loader.py` 38).

## Abweichung vom Plan

**Task 4:** Die neue Schema-Validierung in `validate_profile()` faengt strukturelle
Fehler (fehlendes `name`, falsche Typen, Range-Verletzungen, unknown keys) *frueher*
ab als die bisherige programmatische Validierung. Dadurch aendern sich die
Fehlermeldungen fuer 6 bestehende Tests. Die Tests wurden auf die neuen
Schema-Meldungen umgestellt (gleiche Szenarien, neue Message-Regexes). Der Plan sah
nur das *Hinzufuegen* neuer Schema-Tests vor, nicht die Anpassung bestehender — diese
Anpassung war jedoch notwendig, weil die Schema-Pruefung vor der programmatischen
Validierung greift.

Zusaetzlich wurde der im Plan vorgesehene `import json as json_module` weggelassen,
da `json` in `capability_loader.py` bereits importiert ist und die Zeile ungenutzt
waere.

Alle weiteren Aenderungen entsprechen 1:1 dem Plan.