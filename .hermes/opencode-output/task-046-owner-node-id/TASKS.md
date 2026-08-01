# TASKS — T-046

| ID | Task | Prio | Status |
|---|---|---|---|
| T-046 | Tasks an bestimmte Nodes adressieren (`owner_node_id`) | HIGH | done |

## Sub-Tasks

| # | Task | Status | Commit |
|---|------|--------|--------|
| 1 | Server — `claim_stage()` filtert nach `owner_node_id` | done | `bc70188` |
| 2 | Client — `node-cli task submit --owner <node_id>` | done | `85a7971` |
| 3 | Server deployen + Daemon neustarten | done | — (Deployment) |
| 4 | Board + Doku aktualisieren | done | — (folgt im Doku-Commit) |

## Tests

- `tests/test_scheduler.py::test_claim_stage_respects_owner_node_id` — neu, prüft, dass Node B eine gepinnte Stage überspringt und Node A sie claimen kann.
- `tests/nodes/test_node_cli.py::test_task_submit_with_owner` — neu, prüft, dass `--owner` als `owner_node_id` im Request-Body landet.
- `tests/nodes/test_node_cli.py::test_task_submit_without_owner_omits_field` — neu, prüft, dass das Feld ohne `--owner` nicht im Body steht.
- `tests/nodes/test_node_cli.py::test_all_subcommands_parse_without_errors` — erweitert um einen `--owner`-Case.
- Alle 15 Scheduler-Tests grün; alle 34 node_cli-Tests grün.