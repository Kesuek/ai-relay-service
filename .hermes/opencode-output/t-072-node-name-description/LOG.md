# LOG — T-072: Node-Name + Description per Heartbeat

**Datum:** 2026-07-27
**Plan:** `.hermes/plans/2026-07-27_211500-t-072-node-name-description.md`

## Ablauf

1. **Plan gelesen** — 4 Tasks: Server (Modelle + DB), Node (Heartbeat),
   CLI (Anzeige), Doku.
2. **Code-Reconnaissance** —
   - `src/relay_server/models/__init__.py:351-365` — beide Heartbeat-
     Modelle gefunden.
   - `src/relay_server/core/discovery.py` — `heartbeat()`,
     `list_nodes()`, `get_node()`, `query_nodes_by_capability()`,
     `get_capabilities()`, `_node_row_to_dict()`.
   - `src/relay_server/api/v2/discovery.py` — beide Heartbeat-Routes.
   - `src/relay_server/core/db.py:216-232` — `nodes`-Tabelle ohne
     `description`-Spalte → Migration nötig.
   - `nodes/common/node_cli.py:261-309` — `RelayClient.heartbeat()`,
     `_cmd_node_list`, `_cmd_node_info`.
3. **Task 1 — Server**
   - `HeartbeatRequest`/`NodeHeartbeatRequest` um `node_name` +
     `description` ergänzt (`max_length=128`/`1024`).
   - `nodes`-Tabelle: `description TEXT` im `CREATE TABLE` und
     `ALTER TABLE`-Migration in `_run_migrations()` ergänzt.
   - `heartbeat()`-Signatur um `node_name`/`description` erweitert;
     UPDATE-Block nach `endpoint` eingefügt.
   - Alle SELECTs (`list_nodes`, `get_node`, `query_nodes_by_capability`,
     `get_capabilities`) um `description` ergänzt.
   - `_node_row_to_dict()` um `"description"`-Key ergänzt (defensiv mit
     `in row.keys()`-Check).
   - API-Routes (`/heartbeat`, `/worker-heartbeat`) reichen beide
     Felder an `heartbeat()` weiter.
4. **Task 2 — Node** —
   `RelayClient.heartbeat()` baut `body` mit `node_name`/`description`,
   falls in `self.meta` vorhanden (truthy-Check), und sendet sie mit.
5. **Task 3 — CLI** —
   `_cmd_node_list` gibt `Desc:`-Zeile (gekürzt 60) nach `Caps:` aus;
   `_cmd_node_info` gibt `Description:`-Zeile (voll) nach `Registered:`
   aus.
6. **Task 4 — Doku**
   - `docs/node/capabilities.md` — neuer Abschnitt "Node-level
     `node_name` + `description` (T-072)" mit JSON-Beispiel.
   - `docs/node/cli-reference.md` — `node list`/`node info` um
     Description-Ausgabe ergänzt.
   - `CHANGELOG.md` — T-072-Eintrag unter "Added".
7. **Tests** —
   `pytest tests/test_discovery.py tests/test_db.py tests/test_cli.py tests/nodes/ -x -q`
   → **134 passed**, 0 failed. Keine Regression.
8. **OpenCode-Output** — `STATUS.md`, `TASKS.md`, `DECISIONS.md`,
   `VERIFICATION.md`, `LOG.md` in
   `.hermes/opencode-output/t-072-node-name-description/` abgelegt.

## Abweichungen vom Plan

- **DB-Migration:** Plan erwähnt sie nicht explizit, aber die
  `nodes`-Tabelle hat keine `description`-Spalte. Hinzugefügt im
  `CREATE TABLE` + als idempotente `ALTER TABLE`-Migration in
  `_run_migrations()`. Begründet in DECISIONS.md.
- **Board-Dateien:** `TASKS.md`/`DECISIONS.md`/`PLAN.md` im Repo-Root
  existieren nicht — Schritt entfällt (wie bei T-071). Stattdessen
  werden die Board-Infos im OpenCode-Output-Verzeichnis abgelegt.
- **`_node_row_to_dict`-Check:** Der Plan zeigt `row.get("description")`,
  SQLite-Row-Objekte unterstützen aber kein `.get()`. Implementiert als
  `row["description"] if "description" in row.keys() else None`.

## Offen

- Server-Deploy auf `192.168.2.60` (DB-Migration läuft beim Start).
- Node-CLI-Deploy auf die Worker (damit `node_name`/`description`
  tatsächlich heartbeatet werden).
- Optional: git commit + push.