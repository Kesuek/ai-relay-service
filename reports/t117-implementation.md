# T-117 Umsetzung: `node_cli.py`-Monolith in `cli/`-Submodule aufteilen

Setze den Analyse-Report **`reports/t112-split-analysis.md`** im Repo-Root um (dort steht der vollständige, verbindliche Plan inkl. Schritt-für-Schritt-Anweisung C.6, Risiken C.7 und Constraints-Check C.8). Lies den Report zuerst vollständig. Antworte auf Deutsch, Code-Kommentare/Docstrings Englisch.

## Ziel
`nodes/common/node_cli.py` (1700 Z) aufteilen in die Fassade + 7 `cli/`-Submodule. Einstiegspunkt `node-cli = nodes.common.node_cli:main` UNVERÄNDERT. Alle CLI-Commands erhalten. Volle Test-Suite (419) grün, `tests/nodes/` (162) grün, **ohne eine einzige Test-Änderung**.

## Verboten
- KEINE Änderung an `tests/` — die Mocks (`cli.RelayClient`, `cli.httpx`, `cli.time`, `cli.<KONSTANTE>`, `cli._parse_stage_arg`, `cli.load_meta`, `cli.load_active_profile`, `cli.run_handler`) müssen wie bisher funktionieren.
- KEIN `import` von `node_cli` aus einem Submodul (Zirkularimport + bricht Patches). Submodule importieren nur `node_config`, `node_utils`, `relay_client` und nutzen `httpx`/`time` als Modul-Attribut.
- KEIN `from httpx import ...` oder `from time import ...` in Submodulen — immer `httpx.stream(...)`, `time.sleep(...)`.
- KEIN `from node_config import <KONST>` oder `from node_utils import <KONST>` in Handlern — Konstanten lazy im Funktionskörper über `import nodes.common.node_config as _nc` / `import nodes.common.node_utils as _nu` referenzieren (`_nc.ACTIVE_PATH`, `_nu.REPO_DIR`).

## Verbindliche Architektur (aus Report C.1, C.2, C.3)
- **In der Fassade `node_cli.py` bleiben:** `build_parser`, `main`, `__main__`, `with_client`, `Daemon`-Klasse + `_daemon_start/stop/restart/status/foreground/internal`, `_daemon_dispatch`, `_cmd_status`, `_cmd_reload`, `log`, `PID_PATH`, `LOG_PATH`, alle vorhandenen re-exports (RelayClient, _base_url, _effective_config, _filename_from_response, _setup_logging, _utcnow_str), plus `_parse_stage_arg` re-export aus `cli_task`.
- **In Submodule wandern:**
  - `cli/cli_task.py`: `_parse_stage_arg`, `_cmd_task_submit/result/note/wait`, `_print_task_result`
  - `cli/cli_artifact.py`: `_cmd_artifact_download/upload`
  - `cli/cli_docs.py`: `_html_to_text`, `_cmd_docs`
  - `cli/cli_update.py`: `_cmd_update_check/apply`
  - `cli/cli_capabilities.py`: `_cmd_capabilities_list/validate/publish/diff/current/server/info`, `_print_cap_diff`
  - `cli/cli_node.py`: `_cmd_node_list/info/busy/idle/clear_status/status`, `_save_requested_status`, `_clear_requested_status`
  - `cli/cli_ops.py`: `_cmd_status`, `_cmd_reload` (falls nicht doch in Fassade — Report sagt in Fassade, also nur dort belassen; `cli_ops.py` nur anlegen wenn sinnvoll)
- **`_read_pid`/`_pid_running` → `node_utils.py`** als parametrisiert `read_pid(pid_path)`/`pid_running(pid)`; `node_cli.py` re-exportiert als `_read_pid`/`_pid_running` (Wrapper, Aufrufsignatur identisch). Aufrufer in `node_cli` + Submodulen nutzen die re-exportierten Namen.
- **`cli/__init__.py`:** leer (Paketmarker).
- `node_cli.py` importiert die Submodule für `build_parser`-Referenzen (`set_defaults(func=cli_task._cmd_task_submit)` etc.) — kein Rückimport.

## build_parser-Kopplung
`build_parser()` registriert Subcommands mit `set_defaults(func=<handler>)`. Nach dem Split muss `func` auf die Funktion im Submodul zeigen (z.B. `from nodes.common.cli import cli_task; set_defaults(func=cli_task._cmd_task_submit)`). Fassade re-exportiert alle `_cmd_*` NICHT zwangsläufig — nur die, die Tests direkt aufrufen (`_parse_stage_arg`). Alle `_cmd_*` bleiben über `cli.<name>` NICHT nötig, AUßER falls Tests sie direkt referenzieren — prüfe per `rg "cli\._cmd" tests/nodes/test_node_cli.py` und re-exportiere nur die, die Tests wirklich aufrufen.

## Reihenfolge + Verifikation (Report C.6)
Jeder der Schritte endet mit: `pytest tests/nodes/ -q` → `pytest -q` (volle Suite) → `ruff check nodes/common/ tests/nodes/`. **Nur weiter nach grün.** Wenn ein Schritt rot ist, fixe es und erkläre im Commit-Text.
1. `_read_pid`/`_pid_running` nach `node_utils` (parametrisiert) + re-export in `node_cli`
2. `cli_task` extrahieren (+ re-export `_parse_stage_arg`)
3. `cli_artifact`
4. `cli_docs`
5. `cli_update`
6. `cli_capabilities`
7. `cli_node`
8. `cli_ops` (bzw. in Fassade belassen — Report C.4.4: `_cmd_status`/`_cmd_reload` in Fassade; dann entfällt Schritt 8)
9. `ruff check` + volle Suite + ungenutzte Imports in Fassade aufräumen

## Commits
Jeder Schritt = ein eigener kleiner, revertierbarer Commit. Commit-Message: `refactor(node-cli): split <domain> into cli/<module> (T-117)`. Keine Credentials committen.

## Abschluss
Am Ende liefere in der Konsole aus (keine Datei schreiben außerhalb des Repo — du darfst nur im Repo schreiben):
- Welche Dateien erstellt/geändert wurden
- Test-Ergebnis (volle Suite count)
- ruff-Ergebnis
- Offene Risiken / was du NICHT gemacht hast
