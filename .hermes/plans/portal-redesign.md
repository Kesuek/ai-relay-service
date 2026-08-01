# Plan: Portal + Profilseiten im Community-Mockup-Stil

## Ziel
Portal (`dashboard.html`) und Profilseiten (`node-profile.html`, `user-profile.html`) komplett neu im Design des Community-Mockups (`cluster-community.html`). Gleicher Stil wie das Admin-Dashboard: Nav, Hero, Status-Bar, Cards, Activity-Feed, Footer.

## Design-Vorlage
`.hermes/plans/admin-mockup-reference.html` — das Mockup. Studieren und 1:1 umsetzen.

## Aufgaben

### 1. Portal (`dashboard.html` + `dashboard.js`)
- **Nav-Bar**: Logo, Links (Home, Cluster Status), Admin-Button
- **Hero**: Titel, Beschreibung, Status-Pill (live)
- **Status-Bar**: 5 Items aus `/cluster/overview` (Nodes, Tasks, Stages, Artifacts, Capabilities)
- **Node-Cards**: Banner, Avatar, Name+ID, Status-Dot, Caps, Load-Mini, Meta
- **User-Cards**: Avatar, Name, Role, Meta (status, nodes, joined)
- **Activity-Feed**: Items mit Icon, Highlight-Text, Timestamp
- **Footer**: Version + Links
- `dashboard.js` fetch von `/cluster/overview`, `/cluster/nodes`, `/cluster/users`, `/cluster/activity`

### 2. Node-Profil (`node-profile.html` + `node-profile.js`)
- Nav-Bar mit Back-Link
- Banner + Avatar (groß)
- Name, ID, Status, Load, Queue
- Capability-Liste (mit description, type, input_schema)
- Letzte Tasks (Tabelle)
- Activity (Events für diesen Node)
- Load-Mini-Chart (CSS-only)

### 3. User-Profil (`user-profile.html` + `user-profile.js`)
- Nav-Bar mit Back-Link
- Avatar + Name + Rolle
- Status (active/inactive)
- Zugeordnete Nodes
- Letzte Aktivität

### 4. `cluster.css` — erweitern
- Falls nötig: Profil-spezifische Styles ergänzen (nicht in admin.css)

## Technische Vorgaben
- **Keine inline-style-Attribute** im HTML
- **cluster.css** als einzige Style-Quelle (admin.css nur für Admin-Spezifika)
- **dashboard.js** fetch von `/cluster/*` (öffentliche API)
- **node-profile.js** fetch von `/cluster/nodes/{id}`
- **user-profile.js** fetch von `/cluster/users/{id}`
- Nach dem Schreiben: `node --check` für JS-Syntax

## Reihenfolge
1. Portal (`dashboard.html` + `dashboard.js`)
2. Node-Profil (`node-profile.html` + `node-profile.js`)
3. User-Profil (`user-profile.html` + `user-profile.js`)
4. `cluster.css` ergänzen falls nötig
