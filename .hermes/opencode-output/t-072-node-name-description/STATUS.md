# STATUS — T-072: Node-Name + Description per Heartbeat

**Datum:** 2026-07-27
**Plan:** `.hermes/plans/2026-07-27_211500-t-072-node-name-description.md`

## Ergebnis

Alle vier Tasks aus dem Plan sind abgearbeitet. Implementierung, Tests,
Dokumentation und Output-Ablage abgeschlossen. Deployment des Servers
und des Node-CLIs steht noch aus (siehe "Offen").

| Task | Status |
|------|--------|
| Task 1 — Server: Heartbeat-Modelle + DB-Update | done |
| Task 2 — Node: Heartbeat sendet `node_name` + `description` | done |
| Task 3 — CLI: `node list` + `node info` zeigen Description | done |
| Task 4 — Doku | done |
| Board — TASKS.md / DECISIONS.md / PLAN.md | entfällt (nicht im Repo) |

## Geänderte Dateien

- `src/relay_server/models/__init__.py` — `HeartbeatRequest` /
  `NodeHeartbeatRequest` um `node_name` + `description` ergänzt.
- `src/relay_server/core/db.py` — `nodes.description`-Spalte im
  `CREATE TABLE` und als Migration für bestehende DBs.
- `src/relay_server/core/discovery.py` — `heartbeat()`-Signatur,
  UPDATE-Statements, `_node_row_to_dict()`, alle SELECTs.
- `src/relay_server/api/v2/discovery.py` — beide Heartbeat-Routes
  reichen `node_name` + `description` weiter.
- `nodes/common/node_cli.py` — `RelayClient.heartbeat()` liest
  `node_name`/`description` aus `meta` und sendet sie mit;
  `_cmd_node_list`/`_cmd_node_info` zeigen die Description.
- `docs/node/capabilities.md` — neuer Abschnitt "Node-level
  `node_name` + `description` (T-072)".
- `docs/node/cli-reference.md` — `node list`/`node info` um
  Description-Ausgabe ergänzt.
- `CHANGELOG.md` — T-072-Eintrag unter "Added".

## Commits

(noch nicht committed — Änderungen liegen unstaged im Working-Tree.)

## Offen

- Server-Deploy: `src/relay_server/...` muss auf den LXC-Server
  `192.168.2.60` ausgerollt werden, damit die DB-Migration
  (`ALTER TABLE nodes ADD COLUMN description`) läuft.
- Node-Deploy: `nodes/common/node_cli.py` muss auf die Worker
  ausgerollt werden, damit `node_name`/`description` tatsächlich
  heartbeatet werden (alte CLI sendet die Felder schlicht nicht —
  Server toleriert das, Felder bleiben dann ungesetzt).
- Optional: git commit + push der Änderungen.