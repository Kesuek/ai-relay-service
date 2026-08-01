# STATUS — T-046: Tasks an bestimmte Nodes adressieren

**Datum:** 2026-07-18
**Plan:** `.hermes/plans/2026-07-18_031500-task-046-owner-node-id.md`

## Ergebnis

Alle 4 Tasks aus dem Plan sind abgearbeitet. Implementierung, Tests,
Deployment und Doku-Aktualisierung abgeschlossen.

| Task | Status |
|------|--------|
| Task 1 — Server: `claim_stage()` filtert nach `owner_node_id` | done (commit `bc70188`) |
| Task 2 — Client: `node-cli task submit --owner <node_id>` | done (commit `85a7971`) |
| Task 3 — Server deployen + Daemon neustarten | done (LXC-Server + lokaler Daemon aktiv) |
| Task 4 — Board + Doku aktualisieren | done (STATUS.md, CHANGELOG.md, docs/node/cli-reference.md, docs/reference/api.md) |

## Commits

- `bc70188` — feat: scheduler respects owner_node_id when claiming stages
- `85a7971` — feat: node-cli task submit --owner <node_id>

## Deployment

- `git push` nach `github.com:Kesuek/ai-relay-service.git` (master)
- LXC-Server `192.168.2.60`: `git fetch && git reset --hard origin/master && systemctl --user restart ai-relay-service` → `active`
- Lokaler Daemon: `systemctl --user restart ai-relay-node-cli.service` → `active`

## Abweichungen vom Plan

- Der Plan sah vor, in `claim_stage()` einen Filter einzubauen. Bei der
  Umsetzung zeigte sich, dass die bestehenden Endpunkte
  `POST /scheduler/tasks` und `POST /scheduler/task-simple` bisher
  `owner_node_id = body.owner_node_id or ctx.node_id` gesetzt haben —
  d.h. jeder Task hatte automatisch den Einreicher als Owner und wäre
  damit für jeden anderen Node unsichtbar geworden. Das wurde in
  `src/relay_server/api/v2/scheduler.py` korrigiert: `owner_node_id`
  ist jetzt opt-in (nur gesetzt, wenn der Client es explizit angibt).
  Diese Änderung ist im selben Commit enthalten und im CHANGELOG
  dokumentiert.