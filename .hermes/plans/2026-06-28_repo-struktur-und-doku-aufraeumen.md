# Repo-Struktur & Doku-Aufraeumen — Implementation Plan

> **Fuer OpenCode:** Diesen Plan Task fuer Task abarbeiten. Nach jedem Task: `pytest` laufen lassen und bestaende Tests muessen gruen bleiben.

**Goal:** Das ai-relay-service Repository sauber in Server-Code, Node-Code und zielgruppenspezifische Dokumentation aufteilen. Keine vermischten Tests, keine ueberladene Doku, keine registrierten Node-Skripte im Server-Paket.

**Context:** Das Repository ist historisch gewachsen. 16 Testdateien liegen wild in `tests/`, die `node-readme.md` hat 1053 Zeilen, `node-cli` ist als Server-Console-Script registriert. Nach dieser Aktion ist alles klar getrennt.

**Praemissen:**
- `capability.py` existiert 2x (Server + Node) — das ist gewollt: Server validiert nur, Nodes definieren. Wird nur dokumentiert.
- Nodes werden **nicht** via `pip install -e .` installiert — sie sind eigenstaendige Skripte/Container.
- Keine logischen Aenderungen am Code — nur Struktur, Dokumentation, Trennung.

---

## Task 1: `node-cli` aus `pyproject.toml` entfernen

**Objective:** `node-cli` aus den `[project.scripts]`-Entries entfernen. Es gehoert nicht zum Server-Paket.

**Files:**
- Modify: `pyproject.toml` (Zeile 33)

**Schritt 1: Entry entfernen**

In `pyproject.toml` Zeile 33 aendern von:
```toml
relay-server = "relay_server.main:main"
relay-recovery = "relay_server.cli:main"
node-cli = "nodes.common.node_cli:main"
```
nach:
```toml
relay-server = "relay_server.main:main"
relay-recovery = "relay_server.cli:main"
```

**Schritt 2: Verifizieren**

```bash
cd /home/felix/projects/ai-relay-service
source .venv/bin/activate
pip install -e ".[dev]" 2>&1 | tail -3
which relay-server   # darf noch da sein
which node-cli       # darf NICHT mehr da sein
```

**Schritt 3: Tests laufen lassen**

```bash
cd /home/felix/projects/ai-relay-service
source .venv/bin/activate
.venv/bin/python -m pytest tests/ -x -q 2>&1 | tail -5
```
Erwartet: mindestens 121 passed, 0 failed.

---

## Task 2: Node-Tests nach `tests/nodes/` verschieben

**Objective:** Node-Tests aus dem Server-Test-Verzeichnis raus in ein eigenes `tests/nodes/`. Server-Tests und Node-Tests sind getrennt.

**Files:**
- Move: `tests/test_node_cli.py` → `tests/nodes/test_node_cli.py`
- Move: `tests/test_capability_loader.py` → `tests/nodes/test_capability_loader.py`
- Move: `tests/test_handler_runner.py` → `tests/nodes/test_handler_runner.py`
- Move: `tests/test_example_nodes.py` → `tests/nodes/test_example_nodes.py`
- Modify: `tests/__init__.py` (ggf. anlegen falls nicht vorhanden)
- Create: `tests/nodes/__init__.py`

**Schritt 1: Verzeichnis anlegen**

```bash
mkdir -p /home/felix/projects/ai-relay-service/tests/nodes/
touch /home/felix/projects/ai-relay-service/tests/nodes/__init__.py
```

**Schritt 2: Node-Tests verschieben**

```bash
cd /home/felix/projects/ai-relay-service
git mv tests/test_node_cli.py tests/nodes/
git mv tests/test_capability_loader.py tests/nodes/
git mv tests/test_handler_runner.py tests/nodes/
git mv tests/test_example_nodes.py tests/nodes/
```

**Schritt 3: Import-Pfade in den verschobenen Tests prüfen**

Jede der 4 Dateien öffnen und prüfen ob `sys.path.insert` oder relative Imports auf `nodes.common.*` existieren. Falls `sys.path.insert` mit `../..` oder `../` arbeitet, Pfad anpassen auf die neue Tiefe.

Typisches Muster in `test_node_cli.py`:
```python
# Nach dem Verschieben: Pfad von tests/nodes/ -> nodes/common ist ../../nodes/common
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "nodes" / "common"))
```

**Schritt 4: pyproject.toml Testpfade anpassen**

In `pyproject.toml` Zeile 48 aendern von:
```toml
testpaths = ["tests", "nodes/storage-node/tests"]
```
nach:
```toml
testpaths = ["tests"]
```

**Schritt 5: Node-Tests einzeln laufen**

```bash
cd /home/felix/projects/ai-relay-service
source .venv/bin/activate
.venv/bin/python -m pytest tests/nodes/ -v 2>&1 | tail -10
```
Erwartet: Alle 49 Node-Tests passed.

**Schritt 6: Server-Tests laufen**

```bash
cd /home/felix/projects/ai-relay-service
source .venv/bin/activate
.venv/bin/python -m pytest tests/ -v 2>&1 | tail -10
```
Erwartet: Alle 73 Server-Tests passed (Gesamt 49+73=122 — einer mehr durch weggfallene Filter).

**Schritt 7: Gesamte Suite**

```bash
cd /home/felix/projects/ai-relay-service
source .venv/bin/activate
.venv/bin/python -m pytest tests/ tests/nodes/ -v --tb=short 2>&1 | tail -5
```
Erwartet: 122 passed (oder bestehende Gesamtzahl).

---

## Task 3: `capability.py` Doppelung dokumentieren

**Objective:** Klarstellen warum `capability.py` in beiden Verzeichnissen existiert — Server validiert, Node definiert.

**Files:**
- Modify: `src/relay_server/models/capability.py` (Doc-Kommentar erweitern)
- Modify: `nodes/common/capability.py` (Doc-Kommentar erweitern)

**Schritt 1: Server-seitiges Capability-Modell dokumentieren**

In `src/relay_server/models/capability.py` am Dateianfang folgenden Docstring einfuegen:

```python
"""
Server-side capability data model.

The relay server does NOT define which capabilities exist. Nodes define their
own capabilities in their YAML config / registration payload. The server only
validates the structure of incoming capability definitions and stores them
alongside the node's heartbeat data.

This model is used for:
  - Validating capability fields in registration and heartbeat payloads
  - Schema validation for capability input fields
  - SerDe when reading/writing capability data from/to the database

Nodes use their own copy in nodes/common/capability.py which may have
additional node-specific fields. The two are intentionally separate: nodes
own the capability definition, the server only mediates and routes.
"""
```

**Schritt 2: Node-seitiges Capability-Modell dokumentieren**

In `nodes/common/capability.py` am Dateianfang folgenden Docstring einfuegen:

```python
"""
Node-side capability data model.

Nodes define their capabilities locally, typically in a YAML file
(e.g. nodes/worker/capabilities.yaml). This module loads those definitions
and maps them to the schema expected by the relay server's API.

This model is used for:
  - Loading capability definitions from YAML config files
  - Serializing capabilities for registration and heartbeat payloads
  - Schema validation BEFORE sending to the server (fail fast locally)

The server has its own copy in src/relay_server/models/capability.py for
inbound validation. The two models are intentionally separate: the node
owns the definition, the server only mediates and routes.
The capability_loader.py bridges this gap by loading YAML and mapping to
the server-expected JSON schema.
"""
```

**Schritt 3: Tests laufen lassen**

```bash
cd /home/felix/projects/ai-relay-service
source .venv/bin/activate
.venv/bin/python -m pytest tests/ tests/nodes/ -x -q 2>&1 | tail -5
```
Erwartet: 122 passed.

---

## Task 4: README.md und docs/setup.md entflechten

**Objective:** Ueberschneidungen zwischen `README.md` (Projekt-Ueberblick) und `docs/setup.md` (Installationsanleitung) entfernen.

**Files:**
- Modify: `README.md`
- Modify: `docs/setup.md`

**Schritt 1: README.md straffen**

README.md ist aktuell 255 Zeilen und enthaelt sowohl Ueberblick als auch Setup-Infos. Das README soll nur noch der **Einstiegspunkt** sein:

- Was ist das Projekt? (2-3 Saetze)
- Architektur (aktuelles ASCII-Diagramm, ~20 Zeilen)
- Quickstart (minimal: `pip install -e .` + `relay-server server`)
- Doku-Index (Link auf die wichtigen Docs)
- CI/CD-Status (Tests, Coverage)

Alles was konkrete Setup-Schritte, Token-Lifecycle oder Details beschreibt, wird **entfernt** und durch Links auf `docs/setup.md` ersetzt.

**Konkret:** Section "Documentation" bleibt, Section "Quick Start" bleibt (kurz), Section "Core API" bleibt. Alles darueber hinaus (Phoilosophie, Node-Typen, detaillierte Befehle) muss raus.

Ziel: README.md ca. 80-100 Zeilen.

**Schritt 2: docs/setup.md anpassen**

`sicherstellen dass setup.md die README.md nicht mehr dupliziert`.
- Das Intro "What you get" und "Requirements" sind ok
- Section 10 (Systemd) und 11 (Updating) bleiben
- Troubleshooting und Security Notes bleiben

Pruefen auf Duplikate wie:
- `docs/setup.md:3-12` vs `README.md:1-8` — Beschreibung was der Relay tut
- `docs/setup.md:22-30` vs `README.md:34-44` — git clone + venv + pip install

**Schritt 3: Verifizieren**

```bash
cd /home/felix/projects/ai-relay-service
wc -l README.md docs/setup.md
```
README sollte ~80-100 Zeilen haben. setup.md bleibt bei ~340.

---

## Task 5: `docs/node-readme.md` auf ~200 Zeilen eindampfen

**Objective:** Die Node-Doku von 1053 Zeilen auf ~200 Zeilen reduzieren — nur das Noetigste um einen Node zu verbinden.

**Files:**
- Modify: `docs/node-readme.md` (massives Kürzen)
- Create: `docs/admin/setup.md` (Admin-Doku aus dem Rest der node-readme)
- Create: `docs/node-operator/token-lifecycle.md` (detailliertes Token-Management)
- Create: `docs/node-operator/capabilities.md` (Capabilities definieren)

**Was in node-readme.md bleibt (die ~200 Zeilen):**

```
# AI Relay — Node Connection Guide

## 1. What you need
- Relay URL (z.B. http://192.168.1.50:8788)
- Einen registrierten Node (siehe Section 2)

## 2. Register once
curl-Beispiel mit node_name, endpoint, role, capabilities
→ Save response: node_id, registration_secret, token

## 3. Node state file
ai-relay-agent.json + ai-relay-agent.token Schema

## 4. Wait for activation
Status-Polling bis Admin freigibt

## 5. Heartbeat basics
Ein Heartbeat alle 8s, capabilities mitgeben
→ Verweis auf token-lifecycle.md fuer Details

## 6. Claim work
claim + complete API (2 Beispiele)
→ Verweis auf nodes-design.md fuer Architektur

## 7. Next steps
- Token-Lifecycle: docs/node-operator/token-lifecycle.md
- Capabilities definieren: docs/node-operator/capabilities.md
- Node-Design: docs/nodes-design.md
```

**Schritt 1: node-readme.md als Ganzes neu schreiben**

```bash
# Vorher: wc -l docs/node-readme.md -> 1053
# Nachher: ~200 Zeilen
```

**Schritt 2: Token-Lifecycle-Dokument aus dem Extrakt der alten node-readme schreiben**

Section 5 (Token lifecycle), 8 (Refresh and recover credentials), plus das Schema aus Section 10 in eine eigene Datei `docs/node-operator/token-lifecycle.md`.

~150 Zeilen, enthaelt:
- Token-Arten: temporary (24h), runtime (7d), registration_secret (12h)
- Ablaufdiagramm (ASCII)
- Refresh-Calls mit Beispielen
- Recovery bei Verlust
- Fehlerfaelle (beide abgelaufen → Re-Registrierung)

**Schritt 3: Capabilities-Dokument schreiben**

Aus dem Rest der alten node-readme: Capability-Formate, Suffixe (.native, .ai, .relay), Heartbeat mit Capabilities.

`docs/node-operator/capabilities.md` — ~100 Zeilen.

**Schritt 4: docs/admin/setup.md anlegen**

Aus docs/setup.md + Admin-relevanten Teilen der node-readme:
- Server-Installation (gekürzt, verweist auf setup.md)
- Nodes im Dashboard verwalten
- Admin API (approve, token issue, delete)

**Schritt 5: Doku-Index in README.md aktualisieren**

Nach dem Anlegen der neuen Verzeichnisse den Doku-Index in README.md Section "Documentation" erweitern:

```
| Name | URL | Content | Zielgruppe |
|------|-----|---------|-----------|
| ... (bestehende) ... | | |
| token-lifecycle | /relay/v2/docs/node-operator/token-lifecycle | Token-Arten, Refresh, Recovery | Node-Betreiber |
| capabilities | /relay/v2/docs/node-operator/capabilities | Capabilities definieren und suffigieren | Node-Betreiber |
```

**Schritt 6: Tests laufen lassen (Server startet noch, Docs werden live served)**

```bash
cd /home/felix/projects/ai-relay-service
source .venv/bin/activate
# Docs-API testen
python -c "
from relay_server.api.v2.docs import DOCS_INDEX
for name in ['setup','node-readme','token-lifecycle','capabilities','dashboard','nodes-design','readme']:
    if name in DOCS_INDEX:
        print(f'  ✅ {name}')
    else:
        print(f'  ❌ {name} fehlt')
"
```

---

## Task 6: Setup-Anleitung fuer Worker-Node (Proxmox LXC)

**Objective:** Eine vollstaendige Anleitung zum Einrichten eines AI-Relay Worker-Nodes in einem Proxmox LXC-Container.

**Files:**
- Create: `docs/node-operator/proxmox-worker-setup.md`

**Inhalt (~150 Zeilen):**

```markdown
# Worker-Node Setup — Proxmox LXC

Diese Anleitung beschreibt wie ein Worker-Node in einem Proxmox LXC-Container
eingerichtet wird.

## Voraussetzungen
- Proxmox VE Server (getestet mit v9.x)
- Debian 12 Template
- Relay-Server laeuft bereits (siehe docs/setup.md)

## 1. Container erstellen (optional: Proxmox Web-UI)
Der Worker-Node braucht einen privilegierten Container (keyctl=1):
→ Privilegiert (unprivileged=0) fuer systemd + python-keyring
→ 2 CPU Cores, 1-2 GB RAM, 10 GB RootFS
→ Statische IP: z.B. 192.168.2.50

## 2. Container einrichten
- Benutzer anlegen (z.B. felix/flix2026 → sudo)
- Python 3.11+ installieren
- Abhaengigkeiten: httpx, pyyaml, pydantic

## 3. Node-Registrierung
- Deploy-Skript ausfuehren oder manuell registrieren
- capabilities.yaml definieren

## 4. Node starten
- systemd-Service anlegen (ai-relay.service)
- Heartbeat testen
- Im Dashboard: Node freigeben

## 5. Fehlerbehebung
- 401/403: Token abgelaufen → refresh/re-register
- 404 auf /auth/refresh: Middleware _force_password_change aktiv?
- "Node offline": Heartbeat laeuft nicht
```

---

## Abschliessende Antwort fuers Project Board

Nachdem dieser Plan in OpenCode abgearbeitet wurde, folgende Aenderungen im Project Board (`~/.hermes/projects/ai-relay-service/`) eintragen:

### TASKS.md

| ID | Status | Notiz |
|----|--------|-------|
| T-021 | ✅ done | Tests getrennt |
| T-022 | ✅ done | node-cli aus pyproject.toml entfernt |
| T-023 | ✅ done | capability.py Doppelung dokumentiert |
| T-024 | ✅ done | Doku-Struktur neu organisiert |
| T-025 | ✅ done | README.md + setup.md entflochten |
| T-026 | ✅ done | node-readme.md von 1053 auf ~200 Zeilen |
| T-027 | ✅ done | Proxmox-Worker-Setup-Anleitung |

### DECISIONS.md

```markdown
## 2026-06-28: Repo-Struktur-Aufraeumung

**Entscheidung:** Server-Code (`src/relay_server/`) bleibt unangetastet.
Node-Code (`nodes/`) bleibt eigenstaendiges Verzeichnis ohne
pyproject.toml-Eintrag. Tests werden in `tests/` (Server) und
`tests/nodes/` (Node) getrennt. Dokumentation wird nach Zielgruppe
organisiert: `docs/admin/`, `docs/node-operator/`, `docs/developer/`.

**Grund:** Historisch gewachsene Vermischung von Server- und Node-Code
erschwert Wartbarkeit. Node-Betreiber brauchen andere Docs als Admins.
Der Server ist ein pip-Installierbares Paket — Node-Skripte gehoeren da
nicht als console_scripts rein.

**Betroffene Tasks:** T-021, T-022, T-023, T-024, T-025, T-026, T-027

**Auswirkungen:** node-cli ist nicht mehr via `pip install -e .` verfuegbar.
Muss direkt via `python -m nodes.common.node_cli` oder als systemd-Service
gestartet werden.
```

### PLAN.md

Phase 2 (Streaming-Upload) vorbereiten — die offenen Tasks T-004, T-005, T-014 sind nach dem Doku-Refactoring die naechsten Kandidaten.
