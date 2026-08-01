# VERIFICATION — T-046

## Tests

```
$ .venv/bin/pytest tests/test_scheduler.py tests/nodes/test_node_cli.py -q
49 passed, 7 warnings in 25.02s
```

Relevant neu hinzugefügte Tests:

- `tests/test_scheduler.py::test_claim_stage_respects_owner_node_id`
  - Legt Task mit `owner_node_id="node_a"` an.
  - Node B (gleiche Capability) → `claimed: False`, Stage bleibt `pending`.
  - Node A → `claimed: True`, `claimed_by == node_a_id`.

- `tests/nodes/test_node_cli.py::test_task_submit_with_owner`
  - Mockt `httpx.post` und prüft, dass `owner_node_id` im gesendeten Body steht.

- `tests/nodes/test_node_cli.py::test_task_submit_without_owner_omits_field`
  - Stellt sicher, dass das Feld ohne `--owner`-Flag nicht im Body auftaucht.

- `tests/nodes/test_node_cli.py::test_all_subcommands_parse_without_errors`
  - Erweitert um einen `--owner`-Case für den argparse-Parser.

## Manuelle Verifikation (Deployment)

```
$ ssh felix@192.168.2.60 "systemctl --user is-active ai-relay-service"
active
$ systemctl --user is-active ai-relay-node-cli.service
active
```

Server-Commit auf dem LXC: `85a7971` (`git reset --hard origin/master`).

## Code-Stellen

| Datei | Stelle | Wirkung |
|---|---|---|
| `src/relay_server/core/scheduler.py` (ca. Zeile 281) | Neuer Branch im `claim_stage`-Loop | Überspringt Stage, wenn `task.owner_node_id` gesetzt und != `node_id` |
| `src/relay_server/api/v2/scheduler.py` (Zeile 39, 207) | `owner_node_id=body.owner_node_id` (ohne `or ctx.node_id`) | Owner ist opt-in |
| `nodes/common/node_cli.py` `submit_simple_task` | Neuer Parameter `owner_node_id`, bedingt in Body | Client-Seite |
| `nodes/common/node_cli.py` `p_submit` | Neues Argument `--owner` | CLI-Flag |
| `nodes/common/node_cli.py` `_cmd_task_submit` | Übergibt `owner_node_id=args.owner` | Verdrahtung |