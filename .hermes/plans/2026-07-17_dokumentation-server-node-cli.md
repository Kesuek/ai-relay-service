# Dokumentation: Server-Setup + Node-CLI + Node-Setup — Vollständige Überarbeitung

> **For OpenCode:** `opencode run --agent primary "Abarbeiten von .hermes/plans/2026-07-17_dokumentation-server-node-cli.md" --thinking`

**Goal:** Jedes Feature des Servers und des node-cli muss dokumentiert sein. Es braucht ein vollständiges Server-Setup-Dokument und ein vollständiges Node-Setup-Dokument. Bestehende Docs werden auf Aktualität geprüft, Lücken geschlossen, Broken Links gefixt.

**Architecture:** Die Dokumentation wird in `docs/` konsolidiert. Der README.md bleibt der zentrale Einstiegspunkt. Server-Dokumentation (`docs/setup.md`, `docs/admin/setup.md`, `docs/dashboard.md`) wird auf den aktuellen Code-Stand gebracht. Node-Dokumentation wird neu strukturiert: `docs/node-operator/node-cli-reference.md` (NEU) + bestehende Docs prüfen/aktualisieren. Fehlende verlinkte Docs (`token-lifecycle.md` existiert bereits, `token-concept.md` existiert bereits) werden auf korrekte Pfade geprüft.

**Tech Stack:** Markdown, Python (argparse → CLI-Reference extrahieren)

---

## Task 1: Bestandsaufnahme — existierende Docs auf Broken Links und Aktualität prüfen

**Objective:** Alle `.md`-Dateien im Repo auf Broken Links, veraltete Pfade und fehlende verlinkte Dokumente prüfen.

**Files:**
- Modify: alle `.md`-Dateien in `docs/` und `README.md`

**Step 1: Broken Links identifizieren**

Prüfe in jeder `.md`-Datei:
- `[text](pfad)` — existiert die Zieldatei?
- `[text](../pfad)` — relativ zum Quellverzeichnis auflösen
- `[text](docs/...)` — relativ zum Repo-Root auflösen

Bekannte Broken Links (aus Analyse):
- `docs/node-readme.md` → `[token-lifecycle.md](node-operator/token-lifecycle.md)` — **existiert** ✅ (wurde übersehen)
- `docs/node-readme.md` → `[capabilities.md](node-operator/capabilities.md)` — **existiert** ✅
- `docs/node-readme.md` → `[nodes-design.md](../nodes-design.md)` — **existiert** ✅
- `docs/capabilities.md` → `NODE_CLI_SPEC.md` — **existiert NICHT** ❌ (war nur für OpenCode, nie committed)
- `docs/capabilities.md` → `nodes/common/README.md` — **existiert** ✅
- `README.md` → `docs/token-concept.md` — **existiert** ✅
- `README.md` → `docs/nodes-design.md` — **existiert** ✅
- `docs/setup.md` → `docs/token-concept.md` — **existiert** ✅
- `docs/dashboard.md` → `docs/token-concept.md` — **existiert** ✅

**Step 2: Veraltete Inhalte identifizieren**

Prüfe:
- `STATUS.md` — enthält noch alte Phase-6-Todos (Artifact upload, Credential refresh, YAML validation) die längst erledigt sind
- `BUILDING.md` — völlig veraltet (bezieht sich auf alten Code-Stand, alte Task-IDs T-010–T-020, alte Architektur)
- `docs/setup.md` — §6 Storage-Node verwendet `docker compose` aber der Pfad zu `dist/storage-node-bundle.tar.gz` existiert; Dockerfile existiert nicht im Repo-Root
- `docs/admin/setup.md` — scheint aktuell
- `docs/dashboard.md` — scheint aktuell
- `docs/node-readme.md` — scheint aktuell
- `docs/node-operator/capabilities.md` — verweist auf `NODE_CLI_SPEC.md` (existiert nicht)
- `docs/node-operator/proxmox-worker-setup.md` — scheint aktuell
- `docs/nodes-design.md` — scheint aktuell
- `docs/token-concept.md` — scheint aktuell
- `docs/token-lifecycle.md` — scheint aktuell
- `AGENT_README.md` — scheint aktuell (Kurzform von node-readme)
- `examples/agent-integration/README.md` — scheint aktuell
- `examples/nodes/README.md` — scheint aktuell (markiert als "older iteration")
- `nodes/common/README.md` — scheint aktuell
- `nodes/storage-node/README.md` — scheint aktuell

**Step 3: Fixes dokumentieren**

Erstelle eine Liste aller gefundenen Probleme. Jedes Problem wird in den folgenden Tasks gefixt.

---

## Task 2: `STATUS.md` aktualisieren — Phase 6 als completed markieren

**Objective:** `STATUS.md` enthält noch alte Phase-6-Todos (Artifact upload, Credential refresh, YAML validation) die längst erledigt sind. Auf aktuellen Stand bringen.

**Files:**
- Modify: `STATUS.md`

**Step 1: Phase 6 aktualisieren**

Alte offene Items:
```
- [ ] Artifact upload/download from worker side
- [ ] Credential-refresh daemon (P0)
- [ ] YAML schema validation for capabilities.yaml
```

Ersetzen durch:
```
- [x] Artifact upload/download from worker side (T-001)
- [x] Worker-seitiger Token-Refresh (T-002)
- [x] YAML schema validation for capabilities.yaml (T-003)
- [x] SQLite Lock Contention (T-016)
- [x] Task Timeout enforced (T-017)
- [x] Poller Hard Exit (T-018)
- [x] Inconsistent Logging Levels (T-019)
- [x] Dashboard CSRF Policy dokumentiert (T-020)
- [x] Missing Type Hints (T-021)
- [x] Secrets in Logs vermeiden (T-024)
- [x] Dashboard-Token TTL verkürzen (T-025)
- [x] Capabilities normalisieren (T-026)
- [x] validate_token synchroner DELETE (T-027)
- [x] CRITICAL: Relay stürzt nach ~20s ab — RELAY_SESSION_SECRET fehlte (T-028)
- [x] LOW: Bootstrap-Seite Copy-Button + Login-Link (T-029)
```

**Step 2: Test-Count aktualisieren**

Aktuell: `93/93 passed` — prüfen ob das noch stimmt (nach den vielen Fixes sind es vermutlich mehr).

**Step 3: Code-Review-Summary entfernen oder als historisch markieren**

Die F1–F6 Findings sind alle erledigt. Entweder entfernen oder mit "[historical]" markieren.

---

## Task 3: `BUILDING.md` durch `docs/design-board.md` ersetzen oder als veraltet markieren

**Objective:** `BUILDING.md` ist komplett veraltet (alter Code-Stand, alte Task-IDs, alte Architektur). Es referenziert Tasks T-010–T-020 die es im aktuellen Board nicht mehr gibt.

**Files:**
- Modify: `BUILDING.md`

**Step 1: BUILDING.md als veraltet markieren**

Entweder:
- `BUILDING.md` löschen (wenn niemand mehr drauf verweist)
- Oder einen Header einfügen: `> **DEPRECATED** — This document is outdated. See `docs/setup.md` for server setup, `docs/node-readme.md` for node connection, and `docs/design-board.md` for architecture.`

Prüfe ob irgendeine Datei auf `BUILDING.md` verweist. Wenn nicht → löschen.

---

## Task 4: `docs/node-operator/capabilities.md` — Broken Link zu `NODE_CLI_SPEC.md` fixen

**Objective:** Die `capabilities.md` verweist auf `NODE_CLI_SPEC.md` und `nodes/common/README.md` als "full node-cli command reference". `NODE_CLI_SPEC.md` existiert nicht (war nur für OpenCode). Stattdessen auf die neue `node-cli-reference.md` (Task 5) verweisen.

**Files:**
- Modify: `docs/node-operator/capabilities.md`

**Step 1: Link ersetzen**

Alter Text (Zeile ~117):
```
For the full `node-cli` command reference see `nodes/common/README.md` and `NODE_CLI_SPEC.md`.
```

Neuer Text:
```
For the full `node-cli` command reference see `node-cli-reference.md`.
```

---

## Task 5: `docs/node-operator/node-cli-reference.md` erstellen — Vollständige CLI-Reference

**Objective:** Aus `nodes/common/node_cli.py` die `build_parser()`-Funktion auslesen und eine vollständige Command-Reference erstellen. Jeder Subcommand, jedes Argument, jeder Default-Wert muss dokumentiert sein.

**Files:**
- Create: `docs/node-operator/node-cli-reference.md`

**Step 1: CLI-Struktur aus `build_parser()` extrahieren**

Die `build_parser()`-Funktion (Zeile 989–1108) definiert:

**Global options:**
- `--log-level` — Log level (DEBUG/INFO/WARNING/ERROR). Default: env `RELAY_LOG_LEVEL` or INFO.

**Commands:**

1. **`daemon <action>`** — Control the background daemon.
   - Actions: `start`, `stop`, `restart`, `foreground`, `status`
   - `daemon start` — Start background daemon (writes PID file)
   - `daemon stop` — Stop background daemon
   - `daemon restart` — Restart background daemon
   - `daemon foreground` — Run daemon in foreground (for testing/systemd)
   - `daemon status` — Show daemon status (PID, uptime, last heartbeat)

2. **`heartbeat`** — Send a single heartbeat and exit.

3. **`claim <capability>`** — Claim one stage for a capability.
   - `capability` (positional, required) — Capability name to claim

4. **`complete <stage_id> --task --result-file`** — Complete a claimed stage.
   - `stage_id` (positional, required) — Stage ID to complete
   - `--task` (required) — Task ID of the stage
   - `--result-file` (required) — Path to a JSON file containing the result dict

5. **`task submit --stage --name --priority`** — Submit a single-stage task.
   - `--name` (optional, default: "") — Task name
   - `--stage` (required) — Stage as `<capability>:<json-payload>`
   - `--priority` (optional, default: 0) — Task priority 0-10

6. **`capabilities <action>`** — Capability profile management.
   - Actions: `list`, `validate`, `publish`, `diff`, `current`
   - `capabilities list` — List profiles in `capabilities.d/`
   - `capabilities validate [profile]` — Validate a profile (default: active)
   - `capabilities publish <profile>` — Validate + atomically copy profile to active
   - `capabilities diff [profile]` — Diff working profile vs active
   - `capabilities current` — Show active profile name

7. **`status`** — Print `worker_status.json` content.

8. **`reload`** — Send SIGHUP to running daemon.

9. **`artifact <action>`** — Artifact operations.
   - Actions: `upload`, `download`
   - `artifact upload <file> [--name --task-id --stage-id]`
     - `file` (positional, required) — Path to the file to upload
     - `--name` (optional) — Artifact name (default: filename)
     - `--task-id` (optional) — Optional task ID to associate with
     - `--stage-id` (optional) — Optional stage ID to associate with
   - `artifact download <artifact_id> [-o]`
     - `artifact_id` (positional, required) — The artifact ID to download
     - `--output`, `-o` (optional) — Output path (default: artifact name from server)

**Step 2: Dokument schreiben**

Vollständiges Markdown-Dokument mit:
- Einleitung: was ist node-cli, wie starten
- Global options
- Jeder Command mit: Syntax, Argumenten, Beispielen, Exit-Codes
- Konfiguration (Umgebungsvariablen, Dateipfade)
- Fehlerbehandlung

---

## Task 6: `docs/setup.md` — Storage-Node Docker-Setup auf aktuellen Stand bringen

**Objective:** `docs/setup.md` §6 beschreibt das Storage-Node-Setup. Prüfen ob die Pfade und Befehle noch stimmen.

**Files:**
- Modify: `docs/setup.md`

**Step 1: Prüfen**

- `dist/storage-node-bundle.tar.gz` — existiert der?
- `nodes/storage-node/docker-compose.yml` — existiert?
- `nodes/storage-node/Dockerfile` — existiert?
- `nodes/storage-node/requirements.txt` — existiert?

**Step 2: Ggf. korrigieren**

Wenn Dateien umbenannt oder verschoben wurden, Pfade in der Doku anpassen.

---

## Task 7: `README.md` — Einstiegsdoku auf aktuellen Stand bringen

**Objective:** Der README.md ist der zentrale Einstieg. Prüfen ob alle verlinkten Docs existieren und die Beschreibungen stimmen.

**Files:**
- Modify: `README.md`

**Step 1: Doc-Index-Tabelle prüfen**

Die Tabelle in README.md Zeile 34–45 listet alle Docs. Prüfen:
- `token-lifecycle` → `docs/node-operator/token-lifecycle.md` ✅
- `token-concept` → `docs/token-concept.md` ✅
- `nodes-design` → `docs/nodes-design.md` ✅
- `proxmox-worker-setup` → `docs/node-operator/proxmox-worker-setup.md` ✅
- `capabilities` → `docs/node-operator/capabilities.md` ✅
- Fehlt: `node-cli-reference` → `docs/node-operator/node-cli-reference.md` (NEU)

**Step 2: Eintrag für node-cli-reference ergänzen**

In der Tabelle einen Eintrag hinzufügen:
```
| `node-cli-reference` | `/relay/v2/docs/node-cli-reference` | Full node-cli command reference | Node operator |
```

**Step 3: Test-Count aktualisieren**

README.md sagt "93/93 passed (hard gate)" — prüfen ob das noch stimmt.

---

## Task 8: Tests laufen lassen und verifizieren

**Objective:** Nach allen Änderungen sicherstellen, dass die Tests noch grün sind.

**Files:**
- Keine

**Step 1: Tests ausführen**

```bash
cd ~/projects/ai-relay-service
source .venv/bin/activate
python -m pytest tests/ -x -q
```

Expected: ALL PASSED

---

## Abschliessende Antwort für das Project Board

Nach der Implementierung müssen folgende Änderungen im Project Board `ai-relay-service` nachgetragen werden:

**TASKS.md:**
- Neuen Task anlegen: `T-030` — "Dokumentation: Server + Node-CLI + Node-Setup vollständig überarbeitet" — Prio MID, Status done
- `STATUS.md` aktualisiert (Phase 6 completed, Test-Count korrigiert)
- `BUILDING.md` als deprecated markiert oder gelöscht
- `docs/node-operator/node-cli-reference.md` erstellt
- `docs/node-operator/capabilities.md` Broken Link gefixt
- `README.md` um node-cli-reference-Eintrag ergänzt
- `docs/setup.md` Storage-Node-Pfade geprüft

**DECISIONS.md:**
- Eintrag: "2026-07-17: Dokumentation komplett überarbeitet — BUILDING.md deprecated, node-cli-reference.md neu, alle Broken Links gefixt"

**PLAN.md:**
- Phase 6: `[x]` für alle offenen Items setzen
- Ggf. Phase 7 anlegen: "Dokumentation" mit diesem Task

**IDEAS.md:**
- Keine Änderungen nötig

---

## OpenCode-Output

OpenCode legt sein Ergebnis nach Plan-Abarbeitung ab unter:
```
.hermes/opencode-output/2026-07-17_dokumentation-server-node-cli/
├── STATUS.md         # Was wurde gemacht, was nicht, warum
├── TASKS.md          # tasks aus dem plan mit status
├── DECISIONS.md      # decision-block fuer board
├── VERIFICATION.md   # testergebnisse, diffs, edge cases
└── LOG.md            # vollstaendiges log
```
