# LOG — T-046

## 2026-07-18

### Task 1 — Scheduler-Filter (commit `bc70188`)
- `src/relay_server/core/scheduler.py` `claim_stage()` gelesen (Zeile 256–312).
- Filter-Branch nach dem Dependency-Check eingefügt: Lookup `tasks.owner_node_id`, skip wenn gesetzt und != `node_id`.
- Bei der Durchsicht fiel auf, dass `src/relay_server/api/v2/scheduler.py` (Zeile 39 + 207) bisher `body.owner_node_id or ctx.node_id` als Default setzte — damit hätte der neue Filter alle Tasks für Fremd-Nodes blockiert. Default entfernt (`owner_node_id` jetzt opt-in).
- Test `test_claim_stage_respects_owner_node_id` in `tests/test_scheduler.py` angehängt.
- `pytest tests/test_scheduler.py -x -q` → 15 passed.

### Task 2 — Client `--owner` (commit `85a7971`)
- `RelayClient.submit_simple_task` um Parameter `owner_node_id: str | None = None` erweitert; Body nur bei Bedarf angereichert.
- `p_submit`-Parser um `--owner` ergänzt (Default `None`).
- `_cmd_task_submit` übergibt `owner_node_id=args.owner`.
- Hilfe-Zeile in Modul-Docstring aktualisiert.
- Tests in `tests/nodes/test_node_cli.py`:
  - `test_task_submit_with_owner`
  - `test_task_submit_without_owner_omits_field`
  - `test_all_subcommands_parse_without_errors` (Case erweitert)
- `pytest tests/nodes/test_node_cli.py -x -q` → 34 passed.

### Task 3 — Deployment
- `git push` → master auf GitHub aktualisiert (`6b2a2c7..85a7971`).
- LXC `192.168.2.60`: `git fetch && git reset --hard origin/master && systemctl --user restart ai-relay-service` → `active`.
- Lokal: `systemctl --user restart ai-relay-node-cli.service` → `active`.

### Task 4 — Doku
- `STATUS.md`: Phase 8 angelegt, Test-Count 203 → 205, Commits ergänzt.
- `CHANGELOG.md`: Added-/Changed-Einträge für T-046.
- `docs/node/cli-reference.md`: `task submit` um `--owner` dokumentiert + Beispiel.
- `docs/reference/api.md`: neuer Abschnitt "Pin a task to a specific node".
- Output-Verzeichnis `.hermes/opencode-output/task-046-owner-node-id/` mit STATUS.md, TASKS.md, DECISIONS.md, VERIFICATION.md, LOG.md angelegt.

## Offen

- Doku-Commit für STATUS.md/CHANGELOG.md/docs/* folgt am Ende (Task 4).