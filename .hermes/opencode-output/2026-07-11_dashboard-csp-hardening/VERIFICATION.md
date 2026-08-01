# VERIFICATION.md

## Test-Suite

### Vollständige Suite (Task 4)

```bash
cd /home/felix/projects/ai-relay-service
source .venv/bin/activate
RELAY_SESSION_SECRET="test-session-secret-do-not-use-in-production" \
  .venv/bin/python -m pytest tests/ -q --ignore=tests/test_zeroconf.py --tb=short 2>&1 | tail -10
```

**Ergebnis:**

```
164 passed, 42 warnings in 109.61s (0:01:49)
```

### Test-Suite nach jedem Task

| Task | Suite | Ergebnis |
|------|-------|----------|
| Task 1 (dashboard.js) | `tests/test_dashboard.py` | 25 passed in 10.79s |
| Task 2 (login/bootstrap/change-password.js) | `tests/test_dashboard.py` | 25 passed in 10.95s |
| Task 3 (CSP-Härtung) | `tests/test_dashboard.py` | 25 passed in 10.78s |
| Task 4 (Vollständige Suite) | `tests/` (ohne test_zeroconf) | 164 passed in 109.61s |

Hinweis: `RELAY_SESSION_SECRET` muss gesetzt sein (>= 32 Zeichen), da der
vorige CRITICAL-Fix T-012 den Token-Pepper fail-fast gemacht hat. Dies ist ein
vorgegebenes Test-Setup, nicht durch diese Aenderungen verursacht.

## Statische Verifikation

### CSP-Header (Task 3)

`src/relay_server/main.py` `_SECURITY_HEADERS`:

```python
"Content-Security-Policy": (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    ...
)
```

- `script-src 'self'` — kein `'unsafe-inline'` mehr.
- `style-src 'self' 'unsafe-inline'` — beibehalten wegen Inline-Styles.

Test `test_security_headers_present` verifiziert, dass der CSP-Header gesetzt
ist und `frame-ancestors 'none'` enthaelt (25 passed).

### Inline-Script-Verifikation

Alle vier HTML-Dateien enthalten kein `<script>` mit Inline-Code mehr:

```bash
rg '<script>' src/relay_server/static/*.html
```

Erwartet: Keine Matches (alle `<script>`-Tags sind jetzt
`<script src="/relay/v2/dashboard/static/...js"></script>`).

### onclick-Verifikation

```bash
rg 'onclick=' src/relay_server/static/*.html
```

Erwartet: Keine Matches.

### data-*-Attribut-Verifikation

Dashboard-Buttons verwenden jetzt `data-*`-Attribute:

```bash
rg 'data-node-id|data-user-id|data-group-id|data-tab' src/relay_server/static/dashboard.js
```

Die Event-Delegation-Listener in `dashboard.js` lesen diese Attribute aus
(`btn.dataset.nodeId`, `btn.dataset.userId`, etc.).

## Push-Verifikation

```
git push origin master
```

```
To github.com:Kesuek/ai-relay-service.git
   a3ea839..4c4ffb9  master -> master
```