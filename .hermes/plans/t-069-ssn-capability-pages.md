# Plan: T-069 — SSN `ssn.capability-pages`

## Ziel
Server-Side Node (SSN) als dritten Node-Typ einführen. Ein normaler `node-cli` daemon auf dem Relay-Host heartbeatet `ssn.capability-pages`. Dashboard erkennt ihn und schaltet Menüpunkt frei. HTML-Verwaltung per Task (add/update/delete/list). SSN macht `node-cli task submit` + `node-cli artifact download`. Alte `dashboard_page`-Logik aus dem Server entfernen.

## Änderungen

### 1. Server-Config — `config.py`
```python
# SSN (Server-Side Node)
ssn_enabled: bool = False
ssn_auto_approve: bool = True
ssn_service_unit: str = "ai-relay-ssn.service"
```

### 2. Server `lifespan()` — `main.py`
- Bei `ssn_enabled`:
  - `subprocess.run(["systemctl", "--user", "start", settings.ssn_service_unit])`
  - Bei `ssn_auto_approve`: Node automatisch approven (nach Registrierung)
- Bei shutdown:
  - `subprocess.run(["systemctl", "--user", "stop", settings.ssn_service_unit])`

### 3. systemd-Unit — `systemd/ai-relay-ssn.service` (NEU)
```ini
[Unit]
Description=AI Relay SSN — Server-Side Node
After=ai-relay-service.service
BindsTo=ai-relay-service.service

[Service]
Type=simple
ExecStart=/pfad/zu/.venv/bin/python -m nodes.common.node_cli daemon foreground
Restart=always
Environment=RELAY_BASE_URL=http://127.0.0.1:8788

[Install]
WantedBy=default.target
```

### 4. SSN-Handler — `nodes/handlers/ssn-capability-pages.sh` (NEU)
Handler für `ssn.capability-pages`. Erwartet Payload mit `action`:
- **`add`**: `{action: "add", capability: "image.generate.mflux", artifact_id: "artifact_xxx"}`
  - `node-cli artifact download <artifact_id> --output ~/.ssn/pages/<capability>.html`
- **`update`**: gleicher Mechanismus wie add, überschreibt
- **`delete`**: `{action: "delete", capability: "image.generate.mflux"}`
  - `rm ~/.ssn/pages/<capability>.html`
- **`list`**: `{action: "list"}`
  - Listet `~/.ssn/pages/*.html` auf, gibt JSON-Array der Capability-Namen zurück

### 5. Server-Code bereinigen — Alte `dashboard_page`-Logik entfernen

**`src/relay_server/api/v2/capability_pages.py`** — GANZE DATEI LÖSCHEN
- `GET /relay/v2/capabilities/{name}/dashboard-page` entfernen
- Router aus `__init__.py` entfernen

**`src/relay_server/api/v2/dashboard.py`**:
- `dashboard_page`-Erkennung aus `_enrich_capabilities()` entfernen (Zeilen ~430-443)
- iFrame-Logik aus dashboard.js entfernen

**`src/relay_server/api/v2/storage.py`**:
- `--capability` Parameter für Upload entfernen (Zeilen ~110-130)
- `capability_pages_dir`-Logik entfernen

**`src/relay_server/core/discovery.py`**:
- `dashboard_page` aus Capability-Response entfernen (Zeilen ~296, 340)

**`src/relay_server/models/__init__.py`**:
- `dashboard_page: bool` aus Capability-Modellen entfernen

**`src/relay_server/config.py`**:
- `capability_pages_dir` entfernen

**`src/relay_server/static/dashboard.js`**:
- `c.dashboard_page`-Filter entfernen (Zeile ~90)

### 6. Doku

**`docs/node/ssn.md`** — Finalisieren (Entwurf existiert):
- Was ist ein SSN?
- Capability `ssn.capability-pages`
- HTML-Verwaltung per Task (add/update/delete/list)
- Flow: Dashboard → SSN → Relay → Worker
- Deployment: systemd-Unit + Server-Config

**`docs/node/capabilities.md`** — Überarbeiten:
- `dashboard_page`-Abschnitt entfernen oder durch SSN-Verweis ersetzen
- SSN als Capability-Typ dokumentieren

**`docs/concepts.md`** — SSN als dritten Node-Typ ergänzen:
- "The relay distinguishes three broad categories of node"
- Neuer Abschnitt "Server-side nodes (SSN)"

**`docs/server/setup.md`** — SSN-Config + systemd-Unit ergänzen

### 7. Tests

**`tests/test_ssn.py`** — NEU:
- `test_ssn_handler_add()` — add-Task erzeugt HTML-Datei
- `test_ssn_handler_update()` — update überschreibt
- `test_ssn_handler_delete()` — delete entfernt Datei
- `test_ssn_handler_list()` — list gibt korrekte Liste zurück
- `test_ssn_handler_list_empty()` — list ohne Pages

**`tests/test_dashboard.py`** — Anpassen:
- Tests die `dashboard_page` referenzieren entfernen/aktualisieren

**`tests/test_capability_pages.py`** — GANZE DATEI LÖSCHEN

## Reihenfolge
1. Config + systemd-Unit
2. SSN-Handler
3. Server-Code bereinigen (capability_pages.py löschen, dashboard.py/storage.py/discovery.py/models bereinigen)
4. Dashboard-JS bereinigen
5. Doku
6. Tests
7. `pytest` — alle Tests grün (vorher: alte dashboard_page-Tests raus, neue SSN-Tests rein)
