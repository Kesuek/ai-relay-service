# STATUS — Dashboard CSP-Härtung + JS-Auslagerung

**Datum:** 2026-07-11
**Betroffene Commits:** `4048f4b`, `0964d42`, `4c4ffb9`
**Plan:** `.hermes/plans/2026-07-11_dashboard-csp-hardening.md`

## Zusammenfassung

Alle vier Tasks wurden erfolgreich umgesetzt. `'unsafe-inline'` wurde aus
`script-src` der Content-Security-Policy entfernt, indem saemtliche
Inline-`<script>`-Bloecke und `onclick`-Handler in externe `.js`-Dateien
ausgelagert wurden. Statt `onclick="fn(id)"` werden jetzt `data-*`-Attribute
in Kombination mit Event Delegation verwendet.

Nach jedem Task wurde die Test-Suite ausgefuehrt; alle Tests blieben gruen.
Die vollstaendige Suite (164 Tests, `--ignore=tests/test_zeroconf.py`)
wurde am Ende erneut ausgefuehrt.

| Task | Ziel | Status | Commit |
|------|------|--------|--------|
| Task 1 | dashboard.js — Event Delegation + alle Funktionen auslagern | done | `4048f4b` |
| Task 2 | login.js, bootstrap.js, change-password.js | done | `0964d42` |
| Task 3 | CSP-Härtung — `'unsafe-inline'` aus `script-src` entfernen | done | `4c4ffb9` |
| Task 4 | Vollständige Test-Suite + Push | done | — |

## Betroffene Dateien

- `src/relay_server/static/dashboard.html` (Inline-Script entfernt, onclick→data-*)
- `src/relay_server/static/dashboard.js` (neu)
- `src/relay_server/static/login.html` (Inline-Script entfernt, onclick→data-*)
- `src/relay_server/static/login.js` (neu)
- `src/relay_server/static/bootstrap.html` (Inline-Script entfernt)
- `src/relay_server/static/bootstrap.js` (neu)
- `src/relay_server/static/change-password.html` (Inline-Script entfernt)
- `src/relay_server/static/change-password.js` (neu)
- `src/relay_server/api/v2/dashboard.py` (neue Route `/static/{filename}` zum Ausliefern der JS-Dateien)
- `src/relay_server/main.py` (`'unsafe-inline'` aus `script-src` entfernt)

## Verifikation

Siehe `VERIFICATION.md`. Test-Suite: 164 passed.

## Abweichung vom Plan

Eine Abweichung: Der Plan schlug `<script src="/static/dashboard.js">` vor,
das Dashboard ist aber unter `/relay/v2/dashboard/` gemountet und es gab keine
StaticFiles-Mount. Die Middleware `allowed_prefixes` referenziert bereits
`/relay/v2/dashboard/static/`, daher wurde eine neue Route
`/relay/v2/dashboard/static/{filename}` in `dashboard.py` hinzugefuegt, die
JS-Dateien aus `STATIC_DIR` ausliefert (mit Pfad-Traversal-Schutz). Die
HTML-Dateien referenzieren `/relay/v2/dashboard/static/dashboard.js` etc.

`style-src 'unsafe-inline'` wurde beibehalten, da die HTML-Dateien weiterhin
Inline-`style="..."`-Attribute enthalten (z.B. `style="display:inline"`).
Gemäß Plan-Hinweis ist dies akzeptabel, da das Risiko niedriger ist als bei
script-src und eine Auslagerung der Styles nicht Teil dieser Aufgabe war.