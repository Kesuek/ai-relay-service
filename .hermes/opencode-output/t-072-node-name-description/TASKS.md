# TASKS — T-072

| ID | Task | Prio | Status |
|---|---|---|---|
| T-072 | Node-Name + Description per Heartbeat | HIGH | done |

## Sub-Tasks

| # | Task | Status | Datei(en) |
|---|------|--------|-----------|
| 1.1 | `HeartbeatRequest`/`NodeHeartbeatRequest` um `node_name` + `description` | done | `src/relay_server/models/__init__.py` |
| 1.2 | `nodes.description`-Spalte + Migration | done | `src/relay_server/core/db.py` |
| 1.3 | `heartbeat()`-Signatur + UPDATE-Statements | done | `src/relay_server/core/discovery.py` |
| 1.4 | `_node_row_to_dict()` + SELECTs um `description` | done | `src/relay_server/core/discovery.py` |
| 1.5 | API-Routes reichen `node_name`/`description` weiter | done | `src/relay_server/api/v2/discovery.py` |
| 2 | `RelayClient.heartbeat()` sendet `node_name`/`description` aus `meta` | done | `nodes/common/node_cli.py` |
| 3.1 | `_cmd_node_list` zeigt Description (gekürzt 60) | done | `nodes/common/node_cli.py` |
| 3.2 | `_cmd_node_info` zeigt Description (voll) | done | `nodes/common/node_cli.py` |
| 4 | Doku: capabilities.md, cli-reference.md, CHANGELOG.md | done | `docs/node/*`, `CHANGELOG.md` |

## Tests

- `tests/test_discovery.py`, `tests/test_db.py`, `tests/test_cli.py`,
  `tests/nodes/` zusammen — **134 passed**, keine Regression.
- Manuelle Verifikation gegen den laufenden Server steht noch aus
  (Server-Deploy offen, siehe STATUS.md).