# STATUS — T-071: Node-Info-Befehle + capabilities server Node-ID

**Datum:** 2026-07-27
**Plan:** `.hermes/plans/2026-07-27_063900-t-071-node-commands.md`

## Ergebnis

Alle drei Tasks aus dem Plan sind abgearbeitet. Implementierung, Tests,
Dokumentation und Output-Ablage abgeschlossen. Deployment des Servers steht
noch aus (siehe "Offen"), da die Server-Seite nur die `status="all"`-Semantik
erweitert — die CLI funktioniert dank Client-Fallback auch gegen den aktuell
laufenden Server.

| Task | Status |
|------|--------|
| Task 1 — `capabilities server`/`info` zeigt `node_name (node_id)` | done |
| Task 2 — `node-cli node list` | done |
| Task 3 — `node-cli node info <node_id>` | done |
| Doku — `docs/node/cli-reference.md` + `CHANGELOG.md` | done |
| Board — TASKS.md / DECISIONS.md / PLAN.md | entfällt (nicht im Repo) |

## Commits

(noch nicht committed — Änderungen liegen unstaged im Working-Tree.)

## Offen

- Server-Deploy: `src/relay_server/core/discovery.py` (Behandlung von
  `status="all"`) muss auf den LXC-Server `192.168.2.60` ausgerollt werden,
  damit `node info` nicht auf den Client-Fallback angewiesen ist.
- Optional: git commit + push der Änderungen.