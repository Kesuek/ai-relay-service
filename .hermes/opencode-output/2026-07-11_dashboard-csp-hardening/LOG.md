# LOG.md — Abarbeitung Dashboard CSP-Härtung + JS-Auslagerung

**Start:** 2026-07-11
**Plan:** `.hermes/plans/2026-07-11_dashboard-csp-hardening.md`

## Ablauf

1. **Kontext-Check:** Vor der ersten Aenderung wurden alle im Plan genannten
   Code-Stellen gelesen und gegen den tatsaechlichen Stand abgeglichen:
   - `dashboard.html` (535 Zeilen, Inline-`<script>` ab Zeile 154, diverse
     `onclick`-Handler)
   - `login.html` (75 Zeilen, Inline-`<script>` ab Zeile 62, 2 onclick-Handler)
   - `bootstrap.html` (68 Zeilen, Inline-`<script>` ab Zeile 36)
   - `change-password.html` (85 Zeilen, Inline-`<script>` ab Zeile 41)
   - `main.py` `_SECURITY_HEADERS` (Zeile 25-40, `script-src 'self' 'unsafe-inline'`)
   - `api/v2/dashboard.py` (STATIC_DIR, FileResponse-Routen, keine Static-Route
     fuer JS-Dateien)
   - `tests/test_dashboard.py` (25 Tests)
   Es stellte sich heraus, dass es keine StaticFiles-Mount gibt. Die Middleware
   `allowed_prefixes` referenziert bereits `/relay/v2/dashboard/static/`, aber
   es gab keine Route, die diesen Pfad bedient.

2. **Task 1 (dashboard.js — Event Delegation + alle Funktionen auslagern):**
   - Neue Route `/relay/v2/dashboard/static/{filename}` in `dashboard.py`
     hinzugefuegt (mit Pfad-Traversal-Schutz: `/` und `..` in filename -> 404).
   - `dashboard.js` (neu, ~350 Zeilen) erstellt mit allen Funktionen aus dem
     Inline-Script (`fetchJson`, `postForm`, `delJson`, `showToken`,
     `hideToken`, `copyToken`, `showTab`, `can`, `adminMsg`, `loadMe`,
     `approveNode`, `newToken`, `deleteNode`, `renderAction`, `loadAdmin`,
     `renderUsers`, `renderGroups`, `createUser`, `updateUserGroups`,
     `resetPassword`, `toggleActive`, `deleteUser`, `editGroupPerms`,
     `hidePermModal`, `saveGroupPerms`, `loadAll`).
   - `renderAction(n)`, `renderUsers(u)`, `renderGroups(g)` erzeugen jetzt
     `data-*`-Attribute statt `onclick`: `data-node-id`, `data-node-name`,
     `data-user-id`, `data-active`, `data-group-id`, `data-group-name`.
     Node-Names werden HTML-escaped via `.replace(/"/g, '&quot;')`.
   - `DOMContentLoaded`-Listener bindet Tabs, Refresh, Token-Overlay,
     Permissions-Overlay, CreateUser-Form (`submit` statt `onsubmit`), und
     drei delegierte `document.addEventListener('click', ...)` fuer Node-,
     User- und Group-Aktionen.
   - `dashboard.html`: Inline-`<script>`-Block komplett entfernt, alle
     `onclick`-Attribute entfernt, `data-tab`-Attribute fuer Tabs,
     `<script src="/relay/v2/dashboard/static/dashboard.js">` am Ende von
     `<body>`.
   - pytest `tests/test_dashboard.py`: 25 passed (10.79s).
   - Commit `4048f4b`.

3. **Task 2 (login.js, bootstrap.js, change-password.js):**
   - `login.js` (neu): `showTab()` + `DOMContentLoaded`-Listener fuer Tabs
     (`data-tab`) + Error-Parameter aus URL auslesen.
   - `login.html`: 2 onclick-Handler entfernt, `data-tab`-Attribute gesetzt,
     Inline-`<script>` durch `<script src="...login.js">` ersetzt.
   - `bootstrap.js` (neu): `getCsrfToken()` + `DOMContentLoaded`-Listener, der
     den `submit`-Handler fuer das Form registriert (Bootstrap-Logik 1:1
     aus dem Inline-Script).
   - `bootstrap.html`: Inline-`<script>` durch `<script src="...bootstrap.js">`
     ersetzt.
   - `change-password.js` (neu): `getCsrfToken()` + `DOMContentLoaded`-Listener,
     der `submit`- und `logout`-Handler registriert (Logik 1:1 aus dem
     Inline-Script).
   - `change-password.html`: Inline-`<script>` durch
     `<script src="...change-password.js">` ersetzt.
   - pytest `tests/test_dashboard.py`: 25 passed (10.95s).
   - Commit `0964d42`.

4. **Task 3 (CSP-Härtung — 'unsafe-inline' entfernen):**
   - `main.py` `_SECURITY_HEADERS`: `'unsafe-inline'` aus `script-src`
     entfernt. `style-src 'unsafe-inline'` beibehalten, da die HTML-Dateien
     weiterhin Inline-`style="..."`-Attribute enthalten (z.B.
     `style="display:inline"`, `style="background:#ef4444"`).
   - pytest `tests/test_dashboard.py`: 25 passed (10.78s).
   - Commit `4c4ffb9`.

5. **Task 4 (Vollständige Test-Suite + Push):**
   - Vollstaendige Suite: `164 passed, 42 warnings in 109.61s`.
   - `git push origin master` erfolgreich: `a3ea839..4c4ffb9`.

## Endzustand

164 passed, 42 warnings. Kein Regressions- oder neu eingefuehrter Testfehler.
Drei Commits, einer pro Task. Push erfolgreich.

## Commits

```
4c4ffb9 fix(security): remove 'unsafe-inline' from CSP now that all JS is external
0964d42 refactor(login,bootstrap,change-password): extract JS to external files, remove onclick
4048f4b refactor(dashboard): extract JS to external file, replace onclick with data-* + event delegation
```

## Output

- `STATUS.md`
- `TASKS.md`
- `DECISIONS.md`
- `VERIFICATION.md`
- `LOG.md` (diese Datei)