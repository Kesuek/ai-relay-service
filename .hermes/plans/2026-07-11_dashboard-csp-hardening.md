# Dashboard CSP-Härtung + JS-Auslagerung

> **Fuer OpenCode:** Tasks nacheinander abarbeiten. Nach jedem Task: `pytest` laufen lassen, alle Tests muessen gruen bleiben.

**Goal:** `'unsafe-inline'` aus Content-Security-Policy entfernen, indem alle `onclick`-Handler und Inline-`<script>`-Blöcke in externe `.js`-Dateien ausgelagert werden. Basis für zukünftige Node-View-Erweiterungen (Storage-Node, Board, Wiki, MFlux).

**Betroffene Dateien:**
- `src/relay_server/static/dashboard.html`
- `src/relay_server/static/login.html`
- `src/relay_server/static/bootstrap.html`
- `src/relay_server/static/change-password.html`
- `src/relay_server/static/dashboard.js` (neu)
- `src/relay_server/static/login.js` (neu)
- `src/relay_server/static/bootstrap.js` (neu)
- `src/relay_server/static/change-password.js` (neu)
- `src/relay_server/main.py` (CSP-Header)
- `src/relay_server/api/v2/dashboard.py` (falls static_dir angepasst werden muss)

---

## Task 1: dashboard.js — Event Delegation + alle Funktionen auslagern

**Objective:** Alle `onclick`-Handler und das Inline-`<script>` aus `dashboard.html` in eine externe `dashboard.js` verschieben. Statt `onclick="fn(id)"` werden `data-*`-Attribute + Event Delegation verwendet.

**Files:**
- Modify: `src/relay_server/static/dashboard.html`
- Create: `src/relay_server/static/dashboard.js`

**Vorgehen:**

### 1.1 HTML-Seite vorbereiten

Aus `dashboard.html`:
- `<script>...</script>`-Block (Zeile ~154) komplett entfernen
- Alle `onclick="..."`-Attribute entfernen
- Stattdessen `data-*`-Attribute setzen, z.B.:
  - `<button class="approve-btn" data-node-id="${n.node_id}">Approve</button>`
  - `<button class="token-btn" data-node-id="${n.node_id}">New Token</button>`
  - `<button class="delete-btn" data-node-id="${n.node_id}" data-node-name="${n.node_name}">Delete</button>`
  - `<button class="tab" data-tab="dashboard">Dashboard</button>`
  - `<button class="tab" data-tab="admin">Admin</button>`
  - `<button id="btnRefresh">Refresh</button>` (kein onclick nötig)
  - `<button class="copy-token-btn">Copy to clipboard</button>`
  - `<button class="close-token-btn">Close</button>`
  - `<button class="save-perms-btn">Save Permissions</button>`
  - `<button class="cancel-perms-btn">Cancel</button>`
  - `<button class="save-groups-btn" data-user-id="${u.user_id}">Save Groups</button>`
  - `<button class="reset-pw-btn" data-user-id="${u.user_id}">Reset Password</button>`
  - `<button class="toggle-active-btn" data-user-id="${u.user_id}" data-active="${!u.is_active}">...</button>`
  - `<button class="delete-user-btn" data-user-id="${u.user_id}">Delete</button>`
  - `<button class="edit-perms-btn" data-group-id="${g.group_id}" data-group-name="${g.group_name}">Edit Permissions</button>`
- `<script src="/static/dashboard.js"></script>` am Ende von `<body>` einfügen
- Die Overlay-Divs (`onclick="hideToken()"`, `onclick="hidePermModal()"`) bekommen eine Klasse statt onclick

### 1.2 dashboard.js schreiben

Alle Funktionen aus dem Inline-Script in `dashboard.js`:

```javascript
// dashboard.js — AI-Relay Dashboard
// Keine onclick-Handler im HTML — alles via Event Delegation

document.addEventListener('DOMContentLoaded', () => {
    // Tabs
    document.querySelectorAll('.tab').forEach(el => {
        el.addEventListener('click', () => showTab(el.dataset.tab));
    });

    // Refresh
    document.getElementById('btnRefresh')?.addEventListener('click', loadAll);

    // Token overlay
    document.querySelector('.copy-token-btn')?.addEventListener('click', copyToken);
    document.querySelector('.close-token-btn')?.addEventListener('click', hideToken);
    document.getElementById('tokenOverlay')?.addEventListener('click', hideToken);

    // Permissions overlay
    document.querySelector('.save-perms-btn')?.addEventListener('click', saveGroupPerms);
    document.querySelector('.cancel-perms-btn')?.addEventListener('click', hidePermModal);
    document.getElementById('permOverlay')?.addEventListener('click', hidePermModal);

    // Node actions (Event Delegation auf Container)
    document.addEventListener('click', (e) => {
        const btn = e.target.closest('.approve-btn');
        if (btn) { approveNode(btn.dataset.nodeId); return; }

        const tokenBtn = e.target.closest('.token-btn');
        if (tokenBtn) { newToken(tokenBtn.dataset.nodeId); return; }

        const delBtn = e.target.closest('.delete-btn');
        if (delBtn) { deleteNode(delBtn.dataset.nodeId, delBtn.dataset.nodeName); return; }
    });

    // User actions (Event Delegation)
    document.addEventListener('click', (e) => {
        const groupsBtn = e.target.closest('.save-groups-btn');
        if (groupsBtn) { updateUserGroups(groupsBtn.dataset.userId); return; }

        const resetBtn = e.target.closest('.reset-pw-btn');
        if (resetBtn) { resetPassword(resetBtn.dataset.userId); return; }

        const toggleBtn = e.target.closest('.toggle-active-btn');
        if (toggleBtn) { toggleActive(toggleBtn.dataset.userId, toggleBtn.dataset.active === 'true'); return; }

        const delUserBtn = e.target.closest('.delete-user-btn');
        if (delUserBtn) { deleteUser(delUserBtn.dataset.userId); return; }
    });

    // Group permissions
    document.addEventListener('click', (e) => {
        const editBtn = e.target.closest('.edit-perms-btn');
        if (editBtn) { editGroupPerms(editBtn.dataset.groupId, editBtn.dataset.groupName); return; }
    });

    // Initial load
    loadAll();
});
```

**Wichtig:** Alle bestehenden Funktionsnamen (`showTab`, `approveNode`, `newToken`, `deleteNode`, `copyToken`, `hideToken`, `saveGroupPerms`, `hidePermModal`, `updateUserGroups`, `resetPassword`, `toggleActive`, `deleteUser`, `editGroupPerms`, `loadAll`) bleiben unverändert — nur die Bindung ändert sich von `onclick` zu `addEventListener`.

### 1.3 Tests laufen

```bash
cd /home/felix/projects/ai-relay-service
source .venv/bin/activate
RELAY_SESSION_SECRET="test-session-secret-do-not-use-in-production" .venv/bin/python -m pytest tests/test_dashboard.py -x -q --tb=short 2>&1 | tail -10
```

Expected: ALL PASSED

### 1.4 Commit

```bash
git add src/relay_server/static/dashboard.html src/relay_server/static/dashboard.js
git commit -m "refactor(dashboard): extract JS to external file, replace onclick with data-* + event delegation"
```

---

## Task 2: login.js, bootstrap.js, change-password.js

**Objective:** Gleiches Prinzip für die drei kleineren HTML-Seiten.

**Files:**
- Modify: `src/relay_server/static/login.html`
- Create: `src/relay_server/static/login.js`
- Modify: `src/relay_server/static/bootstrap.html`
- Create: `src/relay_server/static/bootstrap.js`
- Modify: `src/relay_server/static/change-password.html`
- Create: `src/relay_server/static/change-password.js`

### 2.1 login.html → login.js

`login.html` hat:
- `<button onclick="showTab('user')">` und `<button onclick="showTab('seed')">`
- Ein `<script>`-Block mit `showTab()` und Login-Funktionen

Umstellen auf:
```html
<button class="tab" data-tab="user">User Login</button>
<button class="tab" data-tab="seed">Master Seed</button>
<script src="/static/login.js"></script>
```

`login.js`:
```javascript
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.tab').forEach(el => {
        el.addEventListener('click', () => showTab(el.dataset.tab));
    });
});
// showTab() und andere Funktionen aus dem Inline-Script hierher kopieren
```

### 2.2 bootstrap.html → bootstrap.js

Gleiches Muster. Ein `<script>`-Block mit Bootstrap-Logik auslagern.

### 2.3 change-password.html → change-password.js

Gleiches Muster.

### 2.4 Tests laufen

```bash
cd /home/felix/projects/ai-relay-service
source .venv/bin/activate
RELAY_SESSION_SECRET="test-session-secret-do-not-use-in-production" .venv/bin/python -m pytest tests/test_dashboard.py -x -q --tb=short 2>&1 | tail -10
```

Expected: ALL PASSED

### 2.5 Commit

```bash
git add src/relay_server/static/login.html src/relay_server/static/login.js src/relay_server/static/bootstrap.html src/relay_server/static/bootstrap.js src/relay_server/static/change-password.html src/relay_server/static/change-password.js
git commit -m "refactor(login,bootstrap,change-password): extract JS to external files, remove onclick"
```

---

## Task 3: CSP-Härtung — `'unsafe-inline'` entfernen

**Objective:** `'unsafe-inline'` aus `script-src` und `style-src` in `main.py` entfernen.

**Files:**
- Modify: `src/relay_server/main.py`

**Änderung:**

```python
_SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self'; "
        "connect-src 'self'; "
        "img-src 'self' data:; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    ),
    ...
}
```

**Hinweis:** `style-src 'unsafe-inline'` kann auch entfernt werden, wenn keine Inline-Styles im HTML sind. Prüfen ob `<style>`-Tags oder `style="..."`-Attribute im Dashboard-HTML vorkommen. Falls ja, entweder auslagern oder `style-src 'unsafe-inline'` vorerst belassen (niedrigeres Risiko als script).

### 3.1 Tests laufen

```bash
cd /home/felix/projects/ai-relay-service
source .venv/bin/activate
RELAY_SESSION_SECRET="test-session-secret-do-not-use-in-production" .venv/bin/python -m pytest tests/test_dashboard.py -x -q --tb=short 2>&1 | tail -10
```

Expected: ALL PASSED

### 3.2 Commit

```bash
git add src/relay_server/main.py
git commit -m "fix(security): remove 'unsafe-inline' from CSP now that all JS is external"
```

---

## Task 4: Vollständige Test-Suite + Push

```bash
cd /home/felix/projects/ai-relay-service
source .venv/bin/activate
RELAY_SESSION_SECRET="test-session-secret-do-not-use-in-production" .venv/bin/python -m pytest tests/ -q --ignore=tests/test_zeroconf.py --tb=short 2>&1 | tail -10
```

Expected: ALL PASSED

```bash
git push origin master
```

---

## Abschliessende Antwort fuer das Project Board

1. **TASKS.md aktualisieren:**
   - T-022 (CSP 'unsafe-inline' entfernen) → `done`

2. **DECISIONS.md erweitern:**
   - 2026-07-11: Dashboard JS ausgelagert, CSP gehärtet
   - Alle `onclick`-Handler durch `data-*` + Event Delegation ersetzt
   - 4 externe JS-Dateien: `dashboard.js`, `login.js`, `bootstrap.js`, `change-password.js`
   - Basis für zukünftige Node-View-Erweiterungen (Storage, Board, Wiki, MFlux)

## OpenCode-Output

Nach Abarbeitung legt OpenCode sein Ergebnis ab unter:
`.hermes/opencode-output/2026-07-11_dashboard-csp-hardening/`
mit `STATUS.md`, `TASKS.md`, `DECISIONS.md`, `VERIFICATION.md`, `LOG.md`.
