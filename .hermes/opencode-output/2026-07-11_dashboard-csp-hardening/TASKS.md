# TASKS.md — Dashboard CSP-Härtung + JS-Auslagerung

| ID    | Status | Notiz |
|-------|--------|-------|
| T-022 | done | CSP 'unsafe-inline' aus `script-src` entfernt — alle 4 HTML-Seiten (dashboard, login, bootstrap, change-password) verwenden externe `.js`-Dateien, onclick-Handler durch `data-*`-Attribute + Event Delegation ersetzt |