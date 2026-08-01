# VERIFICATION — Review 2026-07-17

## Tests

```bash
cd ~/projects/ai-relay-service
source .venv/bin/activate
python -m pytest tests/ -q
```

**Ergebnis:** `203 passed, 42 warnings in 121.15 s` — Exit 0.

Keine der Änderungen berührt Geschäftslogik. 42 Warnings sind
vorbestehende Deprecation-Hinweise (Pydantic V2 Config, slowapi, httpx),
nicht durch diesen Task verursacht.

## Stichproben-Verifizierung der Doku-Änderungen

- `grep -rn "github.com/felix" docs/ README.md` → keine Treffer mehr
  (Finding #1 erledigt).
- `docs/reference/api.md` enthält den neuen Abschnitt
  "Worked examples (cURL)" mit Error-Code-Tabelle und je einem cURL +
  Response-Block für register, register-admin, heartbeat, claim,
  complete, task (DAG + simple), upload, download, refresh/recover.
- `docs/server/setup.md` enthält neue nummerierte Abschnitte §9 HTTPS/TLS,
  §10 Database, §11 Configuration reference (mit Session-Secret-Rotation +
  Token-Lifecycle-Hinweis), §12 Performance \& scaling; Docker-Option B
  ist als "not yet available" markiert; Troubleshooting-Tabelle erweitert.
- `docs/node/setup.md` enthält den `node-cli`-Klarstellungs-Block mit
  Alias-/Wrapper-Vorschlag, den "Token storage \& permissions"-Abschnitt
  (`chmod 600`, systemd `UMask=0077`, Bind-Mount/Secret-Manager) und eine
  erweiterte Troubleshooting-Tabelle.
- `docs/node/capabilities.md` Handler-Contract als Tabelle mit Exit-Code-,
  Timeout-, SIGKILL-/Shutdown-Verhalten; Naming-Tabelle mit
  "Required for"-Spalte und `.native`-Regel.
- `docs/concepts.md` hat das Glossar am Ende und die KI/AI-Naming-Note.
- `docs/getting-started.md` existiert und ist in
  `src/relay_server/api/v2/docs.py` ALLOWED_DOCS als `getting-started`
  eingetragen → `test_public_docs_index` grün.

## Cross-Link-Konsistenz

Neue/Geänderte Dateien referenzieren existierende Ziele
(`node/setup.md`, `server/setup.md`, `reference/api.md`, `concepts.md`,
`node/token-lifecycle.md`, `node/capabilities.md`,
`node/cli-reference.md`, `getting-started.md`) — alle Ziele vorhanden.