# Review 2026-07-17 — 22 Findings beheben

> **For OpenCode:** `opencode run --agent primary "Abarbeiten von .hermes/plans/2026-07-17_review2-fixes.md" --thinking`

**Goal:** Alle 22 Findings aus dem zweiten GitHub-Review (`review-20260717`) beheben. 4 CRITICAL, 15 MEDIUM, 3 LOW.

---

## Task 1: Fix #1 — `docs/server/admin.md` Clone URL korrigieren

**Files:**
- Modify: `docs/server/admin.md`

**Änderung:** `github.com/felix/` → `github.com/Kesuek/`

---

## Task 2: Fix #2 — `docs/reference/design-board.md` abgeschnittenen Text reparieren

**Files:**
- Modify: `docs/reference/design-board.md`

**Änderung:** Zeile 5 prüfen — `st[...]` ist wahrscheinlich `stages` oder `storage`. Den vollständigen Satz wiederherstellen.

---

## Task 3: Fix #3 — `docs/reference/api.md` mit Payload-Beispielen, Error-Codes und cURL erweitern

**Files:**
- Modify: `docs/reference/api.md`

**Änderung:** Für jeden Endpoint (oder zumindest die wichtigsten: register, heartbeat, claim, complete, task submit, artifact upload) ein cURL-Beispiel mit Payload und Response hinzufügen. Error-Codes dokumentieren.

---

## Task 4: Fix #4 — HTTPS/TLS-Dokumentation in `docs/server/setup.md`

**Files:**
- Modify: `docs/server/setup.md`

**Änderung:** Neuen Abschnitt "HTTPS / TLS" einfügen:
- Relay läuft hinter einem Reverse Proxy (nginx, Caddy, Traefik)
- Empfehlung: Caddy (automatisches Let's Encrypt)
- Beispiel-Konfiguration für Caddy
- Hinweis: Relay selbst hat kein TLS — das ist Aufgabe des Proxys

---

## Task 5: Fix #5 — Datenbank-Persistenz in `docs/server/setup.md`

**Files:**
- Modify: `docs/server/setup.md`

**Änderung:** Neuen Abschnitt "Database" einfügen:
- SQLite + WAL, Speicherort `~/.relay/server.db`
- Backup: `cp` oder `sqlite3 .backup`
- Migrationen: automatisch, additiv (kein Downtime)
- Kein PostgreSQL — Single-Server-Design

---

## Task 6: Fix #6 — Docker-Option B in `docs/server/setup.md` klären

**Files:**
- Modify: `docs/server/setup.md`

**Änderung:** Entweder Docker-Abschnitt entfernen (da kein Dockerfile existiert) oder klarer als "not yet available" markieren.

---

## Task 7: Fix #7 — Console-Script Verwirrung in `docs/node/setup.md`

**Files:**
- Modify: `docs/node/setup.md`

**Änderung:** Klarstellen: `node-cli` ist kein installierter Befehl. Immer `python -m nodes.common.node_cli` verwenden. Oder einen Alias/Shell-Wrapper vorschlagen.

---

## Task 8: Fix #8 — Handler-Fehlerbehandlung in `docs/node/capabilities.md`

**Files:**
- Modify: `docs/node/capabilities.md`

**Änderung:** Handler-Contract erweitern:
- Exit-Codes: 0 = complete, non-zero = `{"error": stderr or "handler exited with code N"}`
- Timeout: `{"error": "handler timeout after Ns"}`
- SIGKILL/Shutdown: stage bleibt claimed, wird vom Scheduler nach timeout freigegeben
- Stdout/Stderr: stdout = result JSON, stderr = logged by daemon

---

## Task 9: Fix #9 — Recovery-Arbeitsablauf in `docs/server/admin.md` klarer machen

**Files:**
- Modify: `docs/server/admin.md`

**Änderung:** Recovery-Abschnitt ausführlicher:
- Was macht `--all`? Deaktiviert alle human admin accounts
- Müssen ALLE deaktiviert sein? Ja, sonst ist master-seed login blockiert
- Recovery ausschalten: Server ohne `RELAY_ENABLE_MASTER_SEED_LOGIN` neustarten

---

## Task 10: Fix #10 — Env-Variablen in `docs/node/cli-reference.md` ergänzen

**Files:**
- Modify: `docs/node/cli-reference.md`

**Änderung:** Prüfen ob `RELAY_ENABLE_MDNS`, `RELAY_SESSION_SECRET` etc. für Nodes relevant sind. Wenn nein, klarstellen dass das Server-only ist.

---

## Task 11: Fix #11 — Konfigurationsoptionen in `docs/server/setup.md`

**Files:**
- Modify: `docs/server/setup.md`

**Änderung:** Alle relevanten Config-Parameter dokumentieren (session_secret, db_path, port, enable_mdns, etc.)

---

## Task 12: Fix #12 — API-Referenz cURL-Beispiele (bereits in Task 3 abgedeckt)

→ merged mit Task 3

---

## Task 13: Fix #13 — Token-Lifecycle in `docs/server/setup.md` erwähnen

**Files:**
- Modify: `docs/server/setup.md`

**Änderung:** Kurzen Satz: "Runtime tokens expire after 7 days. Nodes refresh them automatically. See docs/node/token-lifecycle.md."

---

## Task 14: Fix #14 — Capability-Naming-Konvention konsistent machen

**Files:**
- Modify: `docs/concepts.md` (prüfen ob `.native`-Regel klar ist)
- Modify: `docs/reference/design-board.md` (db-node capabilities prüfen)

**Änderung:** Klarstellen: `.native` suffix für ALLE KI-losen Nodes. `db.board.create.native` ist korrekt.

---

## Task 15: Fix #15 — Troubleshooting erweitern

**Files:**
- Modify: `docs/node/setup.md` (Troubleshooting)
- Modify: `docs/server/setup.md` (Troubleshooting)

**Änderung:** Fehlende Einträge ergänzen:
- Node: Netzwerkfehler, Pfadprobleme, Python-Version, Berechtigungen, systemd, Daemon startet nicht
- Server: DB-Lock, Berechtigungen, Speicherplatz, venv-Probleme, pip-Fehler, Firewall

---

## Task 16: Fix #16 — Session-Secret-Rotation dokumentieren

**Files:**
- Modify: `docs/server/setup.md`

**Änderung:** Abschnitt erweitern: Rotation = neuen Secret generieren, in config.yaml setzen, Server neustarten. Alle Sessions werden ungültig. Empfohlen: nur bei Verdacht auf Kompromittierung.

---

## Task 17: Fix #17 — Token-Storage-Security

**Files:**
- Modify: `docs/node/setup.md`

**Änderung:** Klarstellen: `chmod 600` wird NICHT automatisch gesetzt. Empfehlung: manuell setzen oder im systemd/service-Script. Alternative: env vars (für Container).

---

## Task 18: Fix #18 — Getting-Started-Guides

**Files:**
- Create: `docs/getting-started.md`

**Änderung:** Neues Dokument mit 3 Szenarien:
1. "I just want to run a node" → verweist auf node/setup.md
2. "I want a relay + one node" → server/setup.md + node/setup.md
3. "I want a multi-node cluster" → server/setup.md + node/setup.md + concepts.md

---

## Task 19: Fix #19 — Inkonsistente Begriffe

**Files:**
- Modify: `docs/concepts.md` (Glossar-Abschnitt)

**Änderung:** Begriffsklärung: "KI" (deutsches Konzept-Dokument) vs "AI" (englische API-Doku) — ist beides OK, aber klarstellen. Node-Typen: worker node = KI-capable, service node = KI-less.

---

## Task 20: Fix #20 — `docs/setup.md` und `docs/node-readme.md` sinnvolle Inhalte geben oder löschen

**Files:**
- Modify: `docs/setup.md`
- Modify: `docs/node-readme.md`

**Änderung:** Beide Dateien mit einem Entscheidungsbaum ersetzen: "Was willst du tun?" → Server-Setup / Node-Setup / API nutzen / Konzepte verstehen.

---

## Task 21: Fix #21 — Glossar in `docs/concepts.md`

**Files:**
- Modify: `docs/concepts.md`

**Änderung:** Glossar-Abschnitt am Ende mit Begriffen: Node, Capability, Stage, Task, Runtime Token, Registration Secret, Heartbeat, Claim, Complete, SSE, EventBus, etc.

---

## Task 22: Fix #22 — Performance & Skalierung

**Files:**
- Modify: `docs/server/setup.md`

**Änderung:** Kurzer Abschnitt: "Designed for single-server, small-to-medium clusters (tens of nodes, hundreds of tasks/minute). SQLite handles this comfortably. For larger deployments, consider PostgreSQL (not yet supported)."

---

## Task 23: Tests laufen lassen

```bash
cd ~/projects/ai-relay-service
source .venv/bin/activate
python -m pytest tests/ -q
```

Expected: ALL PASSED

---

## Abschliessende Antwort für das Project Board

**TASKS.md:**
- T-033 — "Review 2026-07-17: 22 Findings behoben" — Prio HIGH, Status done

**DECISIONS.md:**
- Eintrag: "2026-07-17: Zweiter GitHub-Review (review-20260717) — 22 Findings (4 CRITICAL, 15 MEDIUM, 3 LOW) alle behoben"

**IDEAS.md:**
- Umgesetzte Idee ergänzen

---

## OpenCode-Output

```
.hermes/opencode-output/2026-07-17_review2-fixes/
├── STATUS.md
├── TASKS.md
├── DECISIONS.md
├── VERIFICATION.md
└── LOG.md
```
