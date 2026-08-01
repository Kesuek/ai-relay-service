# Plan: Admin Dashboard Redesign — Community Style

## Ziel
Das Admin Dashboard (`/relay/v2/dashboard/admin`) komplett neu im Look des Community Portals (`cluster.css`). Kein Mischmasch mehr — durchgängiges Design mit Cards, Avataren, Load-Bars, Status-Dots, Feed-Listen. Die Admin-Funktionen (Users, Groups, Permissions, Node Approve/Token/Delete) bleiben erhalten, aber in der neuen Optik.

## Design-Vorgabe

Das Community Portal (`dashboard.html`) hat:
- **Nav-Bar** mit Brand-Dot, Links, Buttons
- **Status-Bar** mit `stat`-Cards (label/value/sub)
- **Node-Cards** mit Avatar, Name+ID, Status-Dot, Cap-Tags, Load-Bar, Meta-Zeile
- **Feed-Liste** für Events (`.feed li` mit `.ev-type`, `.ev-time`)
- **Tabellen** nur wo nötig (Tasks, Stages)
- **Cards** mit `.card`, `.card-head`, `.card-title`, `.card-sub`, `.tag`, `.status-dot`
- **Buttons** mit `.btn`, `.btn-primary`, `.btn-danger`, `.btn-muted`
- **Tabs** mit `.tab`, `.tab.active`
- **Modals** mit `.overlay`, `.token-box`, `.ssn-box`

## Aufgaben

### 1. `admin.html` — komplett neu
- Nav-Bar wie Portal (Brand, Portal-Link, Admin-Link active, Refresh, Logout)
- Kein eigener Admin-Header mehr — alles über cluster.css
- Tabs: Dashboard / Admin / Capabilities
- Dashboard-Tab:
  - Summary als `status-bar` mit 4 `stat`-Cards
  - Nodes als Card-Grid (`.grid`) — jede Node eine `.card.clickable` mit Avatar, Name+ID, Status, Caps, Load-Bar, Action-Buttons
  - Tasks als kompakte Tabelle in `.card`
  - Active Stages als kompakte Tabelle in `.card`
  - Events als `.feed`-Liste
  - API Endpoints als Tabelle in `.card`
- Admin-Tab:
  - Users: Create-Form + Tabelle
  - Groups: Tabelle + Permissions-Modal
- Capabilities-Tab:
  - Capability-Card-Grid mit SSN-Page-Badge
- Modals: Token, Permissions, SSN-Page (unverändert)

### 2. `admin.js` — komplett neu
- Gleiche Logik wie bisher, aber:
  - Summary rendert `stat`-Cards (`.stat > .label + .value + .sub`)
  - Nodes rendert Cards (`.card.clickable > .card-head > .avatar + .card-title + .card-sub + .cap-list + .load-bar + Meta`)
  - Events rendert `.feed`-Liste (`.feed li` mit `.ev-type` und `.ev-time`)
  - Admin-Tab (Users/Groups) bleibt Tabellen-basiert (passt für Daten)
  - Alle CSS-Klassen aus `cluster.css` verwenden
  - Keine inline-style-Attribute mehr wo möglich

### 3. `admin.css` — reduzieren
- Nur noch Admin-spezifische Styles:
  - `.admin-msg` (Message-Banner)
  - `.form-row` (Create-User-Form)
  - `.inline-input`, `.inline-select` (Node-Approve-Form)
  - `.approve-btn`, `.token-btn` (Action-Buttons in Cards)
  - `.admin-actions` (Button-Group in User-Tabelle)
  - `.perm-grid` (Permissions-Checkboxen)
  - `.ssn-box` (SSN-Page-Modal)
  - `.token-box` (Token-Modal)
  - `.overlay` (Modal-Hintergrund)
- Alles andere aus `cluster.css` übernehmen (kein Duplikat)

### 4. Tests
- `tests/test_cluster_api.py` bleibt grün
- Manuell prüfen: Admin-Seite lädt, Nodes als Cards, Tabs funktionieren

## Nicht ändern
- API-Endpoints (bleiben)
- Login/Bootstrap/Change-Password-Seiten (bleiben)
- Portal-Seite (bleibt)
- Node/User-Profilseiten (bleiben)
