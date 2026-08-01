# VERIFICATION — T-072

## Automatische Tests

```
.venv/bin/python -m pytest tests/test_discovery.py tests/test_db.py tests/test_cli.py tests/nodes/ -x -q
```

**Ergebnis:** 134 passed, 0 failed, 0 errors (54.48s). Keine Regression
durch die neuen Felder oder die DB-Migration.

## Statische Verifikation

- `import relay_server.core.discovery`,
  `import relay_server.api.v2.discovery`, `import relay_server.models`
  → alle importierbar (Syntax/Typen ok).
- `_node_row_to_dict` enthält `"description"`-Key.
- Beide Heartbeat-Routes übergeben `node_name`/`description` an
  `heartbeat()`.
- `RelayClient.heartbeat()` baut `body` mit `node_name`/`description`,
  falls in `meta` vorhanden.
- `_cmd_node_list` gibt `Desc:`-Zeile bei vorhandenem `description` aus.
- `_cmd_node_info` gibt `Description:`-Zeile bei vorhandenem
  `description` aus.

## Manuelle Verifikation (ausstehend)

Die manuelle Verifikation gegen den laufenden Server steht aus, bis
das Server-Deploy erfolgt ist (siehe STATUS.md "Offen"). Schritte:

1. Server auf `192.168.2.60` ausrollen + neu starten → Migration läuft
   (`ALTER TABLE nodes ADD COLUMN description`).
2. In `~/.relay/ai-relay-agent.json` auf einem Worker `node_name` und
   `description` setzen.
3. `node-cli heartbeat` → Server returned `{"status":"ok"}`.
4. `node-cli node list` → `Desc:`-Zeile erscheint.
5. `node-cli node info <id>` → `Description:`-Zeile erscheint (voll).
6. DB-Check:
   `sqlite3 ~/.relay/relay.db "SELECT node_id, node_name, description FROM nodes WHERE node_id='<id>'"`
   → beide Felder gesetzt.