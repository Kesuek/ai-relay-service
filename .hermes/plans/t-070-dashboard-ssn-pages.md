# Plan: T-070 — Dashboard-Capabilities-Übersicht mit SSN-Pages

## Ziel
Capabilities mit Dashboard-Seite (vom SSN `ssn.capability-pages` verwaltet) bekommen in der Dashboard-Übersicht ein 📄-Symbol und sind klickbar. Dashboard fragt SSN per Task `list` nach verfügbaren Pages, zeigt sie als klickbare Karten an. Klick lädt die HTML vom SSN.

## Änderungen

### 1. Dashboard-Backend — `dashboard.py`
- Neuer Endpoint `GET /relay/v2/dashboard/api/ssn-pages`:
  - Prüft ob `ssn.capability-pages` heartbeatet
  - Submittet einen Task an `ssn.capability-pages` mit `action: list`
  - Gibt die Liste der Capability-Namen zurück
  - Cached das Ergebnis kurz (30s), um nicht bei jedem Seitenaufruf einen Task zu submiten

### 2. Dashboard-Frontend — `dashboard.js`
- Nach dem Laden der Capabilities-Liste: `fetch('/relay/v2/dashboard/api/ssn-pages')`
- Capabilities die in der SSN-Liste sind bekommen:
  - 📄-Icon in der Capability-Karte
  - Klickbar: Klick öffnet die HTML vom SSN in einem iFrame/Modal
- iFrame lädt die HTML über einen neuen Proxy-Endpoint

### 3. SSN-Page-Proxy — `dashboard.py`
- Neuer Endpoint `GET /relay/v2/dashboard/api/ssn-page/{capability}`:
  - Submittet Task an `ssn.capability-pages` mit `action: list`
  - Findet die Capability in der Liste
  - Lädt die HTML vom SSN (oder direkt von `~/.ssn/pages/<capability>.html` auf dem CT)
  - Gibt sie als HTML zurück

### 4. Tests
- `test_dashboard_ssn_pages()` — SSN-Pages-Endpoint gibt korrekte Liste zurück
- `test_dashboard_ssn_page_proxy()` — Proxy lädt HTML für eine Capability
