# TASKS — T-071

| ID | Task | Prio | Status |
|---|---|---|---|
| T-071 | Node-Info-Befehle + capabilities server Node-ID | HIGH | done |

## Sub-Tasks

| # | Task | Status | Datei(en) |
|---|------|--------|-----------|
| 1 | `capabilities server`/`info` zeigt `node_name (node_id)` | done | `nodes/common/node_cli.py` |
| 2 | `node-cli node list` | done | `nodes/common/node_cli.py` |
| 3 | `node-cli node info <node_id>` | done | `nodes/common/node_cli.py` |
| — | Server: `list_nodes(status="all")` als Keyword | done | `src/relay_server/core/discovery.py` |
| — | Doku: cli-reference.md + CHANGELOG.md | done | `docs/node/cli-reference.md`, `CHANGELOG.md` |

## Tests

- `tests/test_discovery.py` — 16 passed (kein Regression durch `status="all"`-Änderung).
- `tests/nodes/test_node_cli.py` + `tests/test_discovery.py` zusammen — 74 passed.
- Manuelle Verifikation gegen den laufenden Server (siehe VERIFICATION.md).