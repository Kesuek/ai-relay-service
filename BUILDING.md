# Building Plan – ai-relay-service

> Zentrale Referenz für den aktuellen Entwicklungsstand und die nächsten Schritte.
> Aktualisiert: 2026-06-26

---

## Projekt-Übersicht

- **Repo:** `~/projects/ai-relay-service`
- **Branch:** `master` (clean nach Commit `4544b65`)
- **Build:** `pip install -e .` im venv `.venv`
- **Start Server:** `relay-server` (Entrypoint: `relay_server.main:main`)
- **Start Worker:** `relay-worker start` (kommend)
- **Tests:** `pytest` → aktuell 43/43 grün

---

## Architektur-Entscheidungen (aktuell final)

| # | Entscheidung | Status |
|---|-------------|--------|
| AD-1 | Input-Schema: flexibel als `dict`, Validierung über `CapabilityInputSchema` | ✅ |
| AD-2 | Capability-Klassen: Server (`models/`) + Worker (`nodes/common/`) getrennt, aber kompatibel | ✅ |
| AD-3 | Validierung: CLI lokal (UX) + Worker (Autorität), Server nur Basis-Check | ✅ |
| AD-4 | Capability-API-Endpoints in `discovery.py` | ✅ |
| AD-5 | Atomic Write für `capabilities.yaml` (CLI) + mtime-Check (Daemon) | ✅ |
| AD-6 | Heartbeat alle 8s, kein File-Read pro Heartbeat, nur bei mtime-Änderung oder SIGHUP | ✅ |

---

## Aktueller Stand

### ✅ Abgeschlossen

| Bereich | Was | Wo |
|---------|-----|----|
| Server-API | Auth v2, SlowAPI, Dashboard, CSRF, Security Headers | `src/relay_server/` |
| Datenbank | SQLite, `nodes`-Tabelle mit `capabilities` JSON-Column | `src/relay_server/core/db.py` |
| Scheduler | Task-Phase-System, Claim/Release/Complete, DAG-Stages | `src/relay_server/api/v2/scheduler.py` |
| Node-Capabilities | `CapabilitySet`, `Capability` Dataclass, YAML-Load | `nodes/common/capability.py` |
| Worker-Daemon | Registrierung, Heartbeat-Loop, Graceful Shutdown, CLI-Stub | `nodes/worker/worker.py` |
| Capability-Template | Beispiel-`capabilities.yaml` mit `script.image.flux` | `nodes/worker/capabilities.yaml` |

### 🔄 In Arbeit

| Bereich | Was | Status |
|---------|-----|--------|
| Data Models (neu) | `models/capability.py` (InputField + Schema + Validierung) | ✅ geschrieben |
| Data Models (neu) | `models/discovery.py` (DiscoveryNode, DiscoveryCapability) | ✅ geschrieben |
| Data Models (neu) | `models/task.py` (SimpleTaskRequest, idempotency) | ✅ geschrieben |
| models/__init__.py | Aufräumen: alte Capability ersetzen, neue importieren | ⬜ offen |

### ⬜ Noch nicht begonnen

| Bereich | Was | Prio |
|---------|-----|------|
| Server Discovery-API | `GET /capabilities`, `GET /capabilities/{name}` | 🔴 P0 |
| Server Simple-Task | `POST /scheduler/task-simple` | 🔴 P0 |
| Worker Input-Validator | Payload gegen input-Schema prüfen | 🔴 P0 |
| Worker Token-Refresh | Credential-Refresh vor Expiry | 🔴 P0 |
| Worker Artifact-Download | Input-Artifacts vor Stage holen | 🟡 P1 |
| Worker SIGHUP + mtime | Capabilities zur Laufzeit neu laden | 🟡 P1 |
| Worker Reconnect | Auto-Reconnect + Re-Register | 🟡 P1 |
| CLI caps write | Atomic Write + Validate | 🔴 P0 |
| CLI task submit | Task absenden mit Server-Discovery | 🔴 P0 |
| CLI caps validate | Schema-Prüfung (lokal) | 🟡 P1 |
| CLI caps show | Capabilities anzeigen (lokal/Server) | 🟢 P2 |
| CLI task watch | Live-Follow eines Tasks | 🟢 P2 |
| CLI config | `~/.relay/config.json` verwalten | 🟡 P1 |

---

## Coding-Session Ablauf (nach opencode-Run-Muster)

### Neue Dateien erstellen

```
opencode run --agent primary "Erstelle die Datei models/__init__.py mit allen Pydantic-Modellen. 
Die alten Capability/Task-Modelle in der Datei müssen durch die neuen aus models/capability.py, 
models/discovery.py und models/task.py ersetzt werden. Importiere alles sauber und stelle 
sicher, dass bestehende Imports aus api/v2/auth.py und api/v2/scheduler.py weiter funktionieren."
```

### Bestehende Server-Endpoints erweitern

```
opencode run --agent primary "Erweitere src/relay_server/api/v2/discovery.py um zwei neue GET-Endpoints:
1. GET /capabilities - gibt DiscoveryResponse zurück (alle Capabilities aller Nodes)
2. GET /capabilities/{name} - gibt DiscoveryDetailResponse zurück

Die Daten kommen aus der SQLite nodes-Tabelle, capabilities-JSON-Spalte. 
Merging: gleiche Capability-Name von verschiedenen Nodes wird zu einem Eintrag mit nodes-Array."
```

### Worker-Daemon erweitern

```
opencode run --agent primary "Erweitere nodes/worker/worker.py um:
1. Input-Validierung vor Task-Ausführung gegen CapabilityInputSchema
2. mtime-Check im Heartbeat-Loop: os.path.getmtime() prüfen, bei Änderung reload
3. SIGHUP-Handler: capabilities.yaml neu laden + sofort Heartbeat senden
4. Error-Handling: bei invalider Capability Exception loggen, stage als failed markieren

Verwende nodes/common/capability.py für CapabilitySet und CapabilityInputSchema."
```

### Worker-CLI erstellen

```
opencode run --agent primary "Erstelle das CLI-Package cli/ mit:
- cli/commands/caps.py: write, validate, show
- cli/commands/tasks.py: submit, list, watch
- cli/client.py: HTTP-Client (RelayClient)
- cli/commands/discover.py: capabilities, nodes

Die CLI verwendet Typer. caps write macht Atomic Write (tmp → validate → mv).
task submit holt Capabilities vom Server, validiert Payload lokal, sendet Task."
```

---

## Build-Aufrufe

```bash
# Full build (im Projektverzeichnis)
pip install -e .

# Tests
pytest -x -q

# Ruff (Linting)
ruff check .

# Einzelnes Modul testen
pytest tests/test_discovery.py -v
```

---

## Vorgaben

- **Python-Version:** 3.11+
- **Formatierung:** Ruff (line-length 100, target py311)
- **Test-Framework:** pytest + pytest-asyncio
- **Docstrings:** Google-Style
- **Commits:** Conventional Commits (`feat:`, `fix:`, `refactor:`)
- **Keine** API-Keys oder Secrets in Code/Config – nur `[REDACTED]`

---

## Task-Referenz

Ausführliche Task-Liste siehe `TASKS.md` (im Projekt-Root).
| ID | Aufgabe | Prio | Status |
|----|---------|------|--------|
| T-010 | Input-Schema Validierung in capability.py | 🔴 | ⬜ todo |
| T-011 | Atomic Write CLI (`caps write`) | 🔴 | ⬜ todo |
| T-012 | mtime-Check + SIGHUP-Reload | 🟡 | ⬜ todo |
| T-013 | Credential-Refresh im Worker | 🔴 | ⬜ todo |
| T-014 | Artifact-Download im Worker | 🟡 | ⬜ todo |
| T-015 | Discovery-API Endpoints | 🔴 | ⬜ todo |
| T-016 | POST /scheduler/task-simple | 🔴 | ⬜ todo |
| T-017 | Worker-CLI task submit | 🟡 | ⬜ todo |
| T-018 | CLI Capability-Cache | 🟢 | ⬜ todo |
| T-019 | Token-Management/Auto-Refresh | 🔴 | ⬜ todo |
| T-020 | Schema-Validierung Input-Constraints | 🟡 | ⬜ todo |