# Plan: T-044 — Community Dashboard

## Scope
Ersetze das bestehende Dashboard durch ein Community-Style Cluster-Portal mit:
- Öffentlicher Landing Page (Overview) — Nav, Hero, Status-Widget, Node-Karten, User-Karten, Activity-Feed
- Node-Profilseiten (öffentlich)
- User-Profilseiten (öffentlich)
- Admin-Bereich bleibt Login-geschützt (unter `/admin/`)
- Kein iFrame mehr für Capability-Seiten — stattdessen Node-Profil-Ansicht

## Tasks

### 1. Neue API-Endpoints (`api/v2/cluster.py`)
Neuer Router `cluster.py` — öffentlich (kein Login erforderlich, Read-only GET):

| Endpoint | Beschreibung |
|----------|-------------|
| `GET /cluster/overview` | Aggregierte Cluster-Metriken + Nodes + aktuelle Events |
| `GET /cluster/nodes` | Liste aller Nodes mit Status, Caps, Load |
| `GET /cluster/nodes/{node_id}` | Node-Profil: Details, Capabilities, letzte Tasks, Status-Historie |
| `GET /cluster/users` | Liste aller human users mit Status |
| `GET /cluster/users/{user_id}` | User-Profil: Details, Nodes, Aktivität |
| `GET /cluster/activity` | Activity Feed (letzte 50 Events) |

Diese Endpoints sind **public read-only** — kein Auth, kein CSRF. Sie exponieren nur Status-Informationen, keine Secrets.

### 2. Dashboard-HTML + JS ersetzen (`static/`)
**`static/dashboard.html`** → wird zum **Cluster Portal** (Community-Seite):

- Navigationsleiste (Overview / Nodes / Users / Capabilities / Events → Sign in / Admin)
- Hero-Bereich mit Cluster-Status-Pill
- Status-Widget (6/8 online, 1,248 tasks, 2 active, 347 artifacts, 12 caps)
- Node-Karten-Grid (Banner, Avatar, Name+ID, Status-Dot, Caps, Load-Bar, Task-Count)
- User-Karten-Grid (Avatar, Name, Role, Status, Node-Count)
- Activity-Feed (Events)
- Footer mit Version + Links

**`static/dashboard.js`** → wird zum **Cluster Portal JS**:
- Fetch von `/cluster/overview`, `/cluster/nodes`, `/cluster/users`, `/cluster/activity`
- Keine Auth-Logik mehr (die bleibt im Admin-Bereich)
- Live-Auto-Refresh (10s)
- Click → Node-Profil / User-Profil / Task-Detail-Modals

### 3. Admin-Bereich (`static/admin*.html` + `static/admin*.js`)
Login-geschützte Admin-Funktionen unter `/relay/v2/dashboard/admin/`:

- Admin-HTML (Users, Groups, Permissions, Nodes approve/delete)
- Admin-JS (Users, Groups, Nodes-Management — ausgelagert aus dashboard.js)
- Bestehende Admin-Logik bleibt erhalten, wird nur in separate Dateien verschoben

### 4. Node-Profil-Seite (`static/node-profile.html`)
Öffentliche Node-Detailseite:
- Banner + Avatar
- Name, ID, Status, Load, Queue
- Capability-Liste (mit input_schema, description, type)
- Letzte Tasks (Tabelle)
- Activity (Events für diesen Node)
- Mini-Load-Chart (CSS-only, keine D3/Chart.js)

### 5. User-Profil-Seite (`static/user-profile.html`)
Öffentliche User-Detailseite:
- Avatar + Name + Rolle
- Status (active/inactive)
- Zugeordnete Nodes
- Letzte Aktivität

### 6. CSS-Refaktor
- **`static/cluster.css`** — NEU: Community-Seite Styles (hero, status-bar, node-cards, user-cards, activity-feed)
- **`static/admin.css`** — NEU: Admin-Styles (Tabellen, Formulare, Modals)
- Bestehende CSS-Inline aus dashboard.html raus in die CSS-Dateien

### 7. Dashboard-Router-Anpassungen (`api/v2/dashboard.py`)
- `GET /` → servt `dashboard.html` (Cluster Portal)
- `GET /admin` → servt `admin.html` (Login-geschützt)
- `GET /node/{node_id}` → servt `node-profile.html`
- `GET /user/{user_id}` → servt `user-profile.html`
- Bestehende `/api/*` Endpoints bleiben (admin)

### 8. Tests
- **`tests/test_cluster_api.py`** — NEU:
  - `test_cluster_overview_public()` — kein Auth nötig
  - `test_cluster_nodes_list()` — Nodes-Struktur korrekt
  - `test_cluster_node_profile()` — Node-Details
  - `test_cluster_users_list()` — Users-Struktur
  - `test_cluster_activity()` — Activity-Feed
- Bestehende Dashboard-Tests bleiben grün (Admin-API)

### 9. Doku
- `docs/server/dashboard.md` — NEU: Community Portal + Admin-Bereich
- `docs/reference/api.md` — 6 neue Public-Endpoints
- `CHANGELOG.md`
- `STATUS.md` (Phase 20)

## Reihenfolge
1. `cluster.py` — 6 neue Public-Endpoints
2. `cluster.css` + `admin.css` — Stylesheets
3. `dashboard.html` → Community Portal (ohne Admin)
4. `admin.html` + `admin.js` — Ausgelagerter Admin-Bereich
5. `node-profile.html` + `user-profile.html` — Detailseiten
6. Dashboard-Router-Anpassungen
7. Tests
8. Doku

## Nicht geändert
- Login/Bootstrap/Change-Password-Seiten (bleiben)
- Admin-API-Endpoints (bleiben)
- SSE-Event-Stream (bleibt)
- `node-cli` / server-seitige Logik

## Project Board Update (nach Abschluss)
- T-044 auf `✅ done`
- PLAN.md: Phase 20
- DECISIONS.md: Eintrag
