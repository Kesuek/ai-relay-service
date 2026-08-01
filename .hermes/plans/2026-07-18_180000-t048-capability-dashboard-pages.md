# T-048: Capability-eigene Dashboard-Seiten — Implementierungsplan

> **For OpenCode:** Abarbeiten dieses Plans Schritt für Schritt. Nach jedem Schritt `pytest` laufen lassen.

**Goal:** Capabilities können eigene HTML-Dashboard-Seiten bereitstellen. Der Node erstellt `dashboard.html` im Capability-Profil-Verzeichnis, lädt sie per `node-cli artifact upload --capability <name>` hoch, der Server speichert sie in `~/.relay/capability-pages/<name>/dashboard.html` (separater Speicher, kein Artifact-Eintrag), und das Dashboard zeigt die Seite in einem iFrame.

**Architecture:**
- Kein neuer API-Endpoint — `POST /relay/v2/storage/upload?capability=<name>` nutzt den existierenden Upload
- Server erkennt `capability`-Parameter → speichert in eigenem Ordner, kein DB-Eintrag in `artifacts`-Tabelle
- Kein `dashboard_artifact_id` im Heartbeat — der Pfad ist deterministisch (`~/.relay/capability-pages/<name>/dashboard.html`)
- Dashboard bekommt neuen Tab "Capabilities" mit iFrame
- T-049 (Artifact Cleanup) fasst die Pages nicht an — separater Speicherort

**Tech Stack:** FastAPI, Python, JavaScript (vanilla), YAML

---

## Schritt 1: Capability-YAML um `dashboard_page` erweitern

**Objective:** `dashboard_page: true` als erlaubtes Feld im Capability-YAML-Profil.

**Files:**
- Modify: `nodes/common/capability_loader.py`

**Step 1.1: JSON Schema erweitern**

In `CAPABILITY_SCHEMA`, unter `properties` in den Items, `dashboard_page` als `{"type": "boolean"}` hinzufügen.

**Step 1.2: Programmatische `allowed`-Liste erweitern**

In `validate_with_schema()`, die `allowed`-Set um `"dashboard_page"` ergänzen.

**Step 1.3: `_NORMALIZED_KEYS` erweitern**

`"dashboard_page"` in `_NORMALIZED_KEYS` aufnehmen.

**Step 1.4: `_normalize_capability()` erweitern**

`dashboard_page` aus raw extrahieren und ins normalisierte Dict aufnehmen (default `False`).

**Verification:**
```bash
cd ~/projects/ai-relay-service
source .venv/bin/activate
python -m pytest tests/nodes/test_capability_loader.py -x -q
```

---

## Schritt 2: `node-cli artifact upload --capability <name>`

**Objective:** Neuer `--capability`-Parameter für `artifact upload`. Der Server speichert die Datei in `~/.relay/capability-pages/<name>/dashboard.html` statt im Artifact-Store.

**Files:**
- Modify: `nodes/common/node_cli.py` — `_cmd_artifact_upload()` + Argument-Parser
- Modify: `nodes/common/node_cli.py` — `RelayClient.upload_artifact()` — `capability`-Parameter
- Modify: `src/relay_server/api/v2/storage.py` — `storage_upload()` — `capability`-Query-Parameter

**Step 2.1: `RelayClient.upload_artifact()` erweitern**

`capability: Optional[str] = None` Parameter hinzufügen. Wenn gesetzt, als Query-Parameter `?capability=<name>` mitsenden.

**Step 2.2: `_cmd_artifact_upload()` erweitern**

`--capability` Argument hinzufügen, an `client.upload_artifact()` durchreichen.

**Step 2.3: `storage_upload()` in storage.py erweitern**

`capability: Optional[str] = Query(None)` hinzufügen. Wenn gesetzt:
- Zielpfad: `settings.capability_pages_dir / name / "dashboard.html"`
- Datei dorthin schreiben (streaming, wie bei Artifacts)
- **Kein** `store_artifact_from_file()`-Aufruf
- Response: `{"status": "ok", "path": "capability-pages/<name>/dashboard.html"}`

**Step 2.4: Config erweitern**

In `src/relay_server/config.py`: `capability_pages_dir: Path = BASE_DIR / "capability-pages"` hinzufügen.

**Verification:**
```bash
# Manuell:
curl -X POST -F "file=@dashboard.html" "http://localhost:8788/relay/v2/storage/upload?capability=image.generate.mflux"
# → {"status": "ok", "path": "capability-pages/image.generate.mflux/dashboard.html"}
# Prüfen: ~/.relay/capability-pages/image.generate.mflux/dashboard.html existiert
```

---

## Schritt 3: Server servt HTML unter `/relay/v2/capabilities/<name>/dashboard-page`

**Objective:** Neuer GET-Endpoint der die HTML-Datei aus `~/.relay/capability-pages/<name>/dashboard.html` servt.

**Files:**
- Create: `src/relay_server/api/v2/capability_pages.py` — neuer Router
- Modify: `src/relay_server/main.py` — Router registrieren
- Modify: `src/relay_server/config.py` — `capability_pages_dir` (falls in Schritt 2 nicht gemacht)

**Step 3.1: Neuen Router `capability_pages.py`**

```python
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from relay_server.config import settings

router = APIRouter()

@router.get("/{name}/dashboard-page")
async def get_capability_dashboard_page(name: str):
    """Serve the dashboard HTML page for a capability."""
    page_path = settings.capability_pages_dir / name / "dashboard.html"
    if not page_path.exists():
        raise HTTPException(status_code=404, detail="No dashboard page for this capability")
    return FileResponse(
        str(page_path),
        media_type="text/html",
        headers={"X-Frame-Options": "SAMEORIGIN"},
    )
```

**Step 3.2: Router in main.py registrieren**

```python
from relay_server.api.v2.capability_pages import router as capability_pages_router
app.include_router(capability_pages_router, prefix="/relay/v2/capabilities", tags=["capability-pages"])
```

**Verification:**
```bash
python -m pytest tests/ -x -q
# Manuell:
curl -s http://localhost:8788/relay/v2/capabilities/image.generate.mflux/dashboard-page
# → HTML oder 404
```

---

## Schritt 4: Dashboard zeigt klickbare Capabilities mit iFrame

**Objective:** Capabilities mit `dashboard_page: true` werden im Dashboard als klickbare Karten angezeigt. Klick öffnet iFrame mit der Capability-Seite.

**Files:**
- Modify: `src/relay_server/static/dashboard.html` — neuen Tab "Capabilities" + iFrame-Container
- Modify: `src/relay_server/static/dashboard.js` — Capabilities laden, rendern, iFrame-Ansicht

**Step 4.1: HTML erweitern**

Neuen Tab-Button "Capabilities" und Container:

```html
<button id="tabCapabilities" class="tab" data-tab="capabilities">Capabilities</button>

<div id="viewCapabilities" class="hidden">
  <div class="section">
    <h2>Capability Pages</h2>
    <div id="capabilityCards" class="grid"></div>
  </div>
  <div id="capabilityFrame" class="hidden section">
    <button id="btnBackToCaps" class="refresh" style="margin-bottom:.5rem;">← Back</button>
    <iframe id="capabilityIframe" style="width:100%; height:80vh; border:none; border-radius:.75rem; background:white;"></iframe>
  </div>
</div>
```

**Step 4.2: JavaScript erweitern**

```javascript
async function loadCapabilities() {
  try {
    const data = await fetchJson('/relay/v2/discovery/capabilities?available=true');
    const caps = (data.capabilities || []).filter(c => c.dashboard_page);
    const container = document.getElementById('capabilityCards');
    container.innerHTML = caps.map(c => `
      <div class="card" style="cursor:pointer;" data-cap-name="${c.name}">
        <h2>${c.name}</h2>
        <p style="color:var(--muted); font-size:.85rem;">${c.description || 'No description'}</p>
        <span class="tag">${c.type || 'unknown'}</span>
      </div>
    `).join('') || '<p style="color:var(--muted);">No capabilities with dashboard pages.</p>';
  } catch (err) { console.error(err); }
}

function showCapabilityPage(name) {
  document.getElementById('viewCapabilities').classList.add('hidden');
  document.getElementById('capabilityFrame').classList.remove('hidden');
  document.getElementById('capabilityIframe').src = `/relay/v2/capabilities/${encodeURIComponent(name)}/dashboard-page`;
}
```

**Step 4.3: Discovery-Response muss `dashboard_page` enthalten**

`DiscoveryCapability`-Modell in `src/relay_server/models/__init__.py` um `dashboard_page: bool = False` erweitern.
`get_capabilities()` in `discovery.py` muss `dashboard_page` aus der Capability-Definition übernehmen.

**Verification:**
- Dashboard im Browser öffnen
- Capabilities-Tab zeigt Capabilities mit `dashboard_page: true`
- Klick öffnet iFrame

---

## Schritt 5: Tests

**Objective:** Tests für den neuen Endpoint und die erweiterten Modelle.

**Files:**
- Create: `tests/test_capability_pages.py`

**Step 5.1: Capability-Pages-Test**

```python
def test_dashboard_page_not_found(client):
    resp = client.get("/relay/v2/capabilities/nonexistent/dashboard-page")
    assert resp.status_code == 404

def test_dashboard_page_served(client, tmp_path, settings):
    # Page anlegen
    page_dir = settings.capability_pages_dir / "test-cap"
    page_dir.mkdir(parents=True)
    (page_dir / "dashboard.html").write_text("<html><body><h1>Test</h1></body></html>")
    resp = client.get("/relay/v2/capabilities/test-cap/dashboard-page")
    assert resp.status_code == 200
    assert b"<h1>Test</h1>" in resp.content
```

**Verification:**
```bash
python -m pytest tests/test_capability_pages.py -x -q
python -m pytest tests/ -x -q  # alle Tests
```

---

## Schritt 6: Dokumentation

**Objective:** Die neue Funktionalität an allen relevanten Stellen dokumentieren.

**Files:**
- Modify: `docs/node/cli-reference.md` — `artifact upload --capability` dokumentieren
- Modify: `docs/node/capabilities.md` — `dashboard_page`-Feld dokumentieren
- Modify: `docs/reference/api.md` — `?capability=` Query-Parameter bei `POST /upload`
- Modify: `CHANGELOG.md` — Eintrag für T-048

**Step 6.1: CLI-Reference**

In der `artifact upload`-Sektion `--capability <name>` als neuen Parameter aufnehmen:
> `--capability <name>` — Wenn gesetzt, wird die Datei als Dashboard-Seite für die angegebene Capability gespeichert (in `~/.relay/capability-pages/<name>/dashboard.html` auf dem Server). Die Capability muss `dashboard_page: true` im YAML-Profil setzen.

**Step 6.2: Capabilities-Doku**

In der Feld-Referenz `dashboard_page` dokumentieren:
> `dashboard_page: true|false` (optional, default `false`) — Wenn `true`, kann diese Capability eine HTML-Dashboard-Seite bereitstellen. Die Seite wird per `node-cli artifact upload <file> --capability <name>` hochgeladen und im Dashboard in einem iFrame angezeigt.

**Step 6.3: API-Reference**

Bei `POST /relay/v2/storage/upload` den `capability`-Query-Parameter dokumentieren.

**Step 6.4: CHANGELOG**

```
### Added
- T-048: Capability-eigene Dashboard-Seiten — `dashboard_page`-Feld im YAML-Profil,
  `node-cli artifact upload --capability <name>`, Dashboard-Tab mit iFrame
```

---

## Abschliessende Antwort fuer das Project Board

Nach erfolgreicher Implementierung:

- **T-048** → `✅ done`
- **DECISIONS.md:** Eintrag ergänzen dass die Implementierung abgeschlossen ist
- **PLAN.md:** Phase 9 Checkbox für T-048 abhaken
- **IDEAS.md:** Idee "Capability-eigene Dashboard-Seiten" als umgesetzt markieren
- **T-049** bleibt offen (Artifact Cleanup — wird separat gemacht)

## OpenCode-Output

OpenCode legt sein Ergebnis ab in:
`.hermes/opencode-output/t048-capability-dashboard-pages/`
mit `STATUS.md`, `TASKS.md`, `DECISIONS.md`, `VERIFICATION.md`, `LOG.md`.
