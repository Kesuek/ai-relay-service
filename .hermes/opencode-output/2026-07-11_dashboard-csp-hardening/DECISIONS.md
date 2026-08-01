# DECISIONS.md

## 2026-07-11: Dashboard JS ausgelagert, CSP gehärtet

**Entscheidung:** Saemtliche Inline-`<script>`-Bloecke und `onclick`-Handler
wurden aus den vier Dashboard-HTML-Seiten in externe `.js`-Dateien ausgelagert.
Statt `onclick="fn(id)"` werden `data-*`-Attribute in Kombination mit Event
Delegation verwendet (`document.addEventListener('click', ...)` +
`e.target.closest('.class')`). Die Content-Security-Policy wurde entsprechend
gehärtet: `'unsafe-inline'` wurde aus `script-src` entfernt.

- **4 externe JS-Dateien:** `dashboard.js`, `login.js`, `bootstrap.js`,
  `change-password.js` — alle unter `src/relay_server/static/`.
- **Neue Static-Route:** `/relay/v2/dashboard/static/{filename}` in
  `dashboard.py` liefert die JS-Dateien aus (mit Pfad-Traversal-Schutz via
  `/`- und `..`-Check).
- **Event Delegation:** Node-Aktionen (approve, new token, delete) und
  User-Aktionen (save groups, reset password, toggle active, delete) werden
  ueber delegierte Click-Listener auf `document` abgefangen, die
  `data-node-id` / `data-user-id` / `data-group-id`-Attribute auslesen.
- **`style-src 'unsafe-inline'` beibehalten:** Die HTML-Dateien enthalten
  weiterhin Inline-`style="..."`-Attribute (z.B. `style="display:inline"`).
  Gemäß Plan-Hinweis ist dies akzeptabel, da das Risiko niedriger ist als bei
  script-src und eine Auslagerung der Styles nicht Teil dieser Aufgabe war.

**Grund:** `'unsafe-inline'` in `script-src` erlaubt XSS-Angriffe durch
injiziertes JavaScript. Durch die Auslagerung in externe Dateien und die
Verwendung von Event Delegation koennen Angreifer keine Inline-Script-Tags
mehr einschleusen, die der Browser ausfuehren wuerde. Dies ist die Basis fuer
zukuenftige Node-View-Erweiterungen (Storage-Node, Board, Wiki, MFlux), die
nun auf einer sauberen CSP-konformen Architektur aufbauen koennen.

**Betroffene Files:** `dashboard.html`, `dashboard.js`, `login.html`,
`login.js`, `bootstrap.html`, `bootstrap.js`, `change-password.html`,
`change-password.js`, `api/v2/dashboard.py`, `main.py`
**Betroffene Tasks:** T-022