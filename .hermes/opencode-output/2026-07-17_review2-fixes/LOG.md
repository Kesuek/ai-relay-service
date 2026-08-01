# LOG — Review 2026-07-17 Abarbeitung

## 2026-07-17 — OpenCode primary agent

Plan: `.hermes/plans/2026-07-17_review2-fixes.md`
Ziel: Alle 22 Findings aus dem zweiten GitHub-Review (`review-20260717`)
beheben.

### Ablauf

1. Plan gelesen; Bestand: 22 Tasks + Tests + Output-Ordner.
2. Source-Verifikation: `src/relay_server/config.py`, `models/__init__.py`,
   `api/v2/auth.py`, `api/v2/docs.py` gelesen, um Config-Parameter,
   API-Schemas und die Docs-Whitelist zu verifizieren. Existierende
   Doku-Dateien (`docs/{concepts,setup,node-readme}.md`,
   `docs/{server,node,reference}/*.md`) gelesen.
3. Todos (24 Einträge) angelegt und Tasks nacheinander abgearbeitet:
   - T1: admin.md Clone URL `felix`→`Kesuek`.
   - T2: design-board.md Zeile 5 geprüft — vollständig (bereits in
     `6a9c83e` korrekt). Keine Aktion.
   - T3+T12: api.md "Worked examples (cURL)"-Abschnitt mit Error-Code-
     Tabelle, Rate-Limits und je cURL+Response für die 10 wichtigsten
     Endpunkte.
   - T4: setup.md §9 HTTPS/TLS mit Caddy/nginx/Traefik + SSE- und
     Cookie-Hinweise.
   - T5: setup.md §10 Database (SQLite+WAL, Backup kalt/heiss, Recovery).
   - T6: setup.md Docker-Option B → "not yet available".
   - T7: node/setup.md `node-cli`-Klarstellung + Alias/Wrapper-Vorschlag.
   - T8: capabilities.md Handler-Contract als Tabelle (Exit-Codes,
     Timeout, SIGKILL, stdout/stderr-Trennung).
   - T9: admin.md Recovery-Abschnitt: was `--all` macht, warum Pflicht,
     Recovery ausschalten.
   - T10: cli-reference.md Server-only-Env-Vars gekennzeichnet.
   - T11: setup.md §11 Configuration reference mit YAML-Beispiel.
   - T13: setup.md Token-Lifecycle-Kurzverweis (7 Tage, auto-refresh).
   - T14: `.native`-Regel in concepts.md, capabilities.md und
     design-board.md (db-node-Liste) konsistent gemacht.
   - T15: Troubleshooting-Tabellen in server/setup.md und node/setup.md
     erweitert (DB-Lock, Firewall, venv, systemd, Berechtigungen, …).
   - T16: setup.md Session-Secret-Rotation (Schritte + "alle Sessions
     ungültig").
   - T17: node/setup.md "Token storage \& permissions" (chmod 600, systemd
     UMask, Bind-Mount, Secret-Manager). Währenddessen festgestellt, dass
     `RELAY_RUNTIME_TOKEN` vom Node-CLI nicht ausgewertet wird → Doku
     korrekt als "not yet honoured" markiert statt falsche Funktion zu
     dokumentieren.
   - T18: docs/getting-started.md neu (3 Szenarien + Decision Tree);
     Eintrag in docs.py Whitelist.
   - T19: concepts.md KI/AI-Begriffsklärung + worker/service-node-Synonyme.
   - T20: docs/setup.md und docs/node-readme.md zu Entscheidungsbaum-
     Templates ausgebaut.
   - T21: concepts.md Glossar (20 Begriffe).
   - T22: setup.md §12 Performance \& scaling.
4. `python -m pytest tests/ -q` → **203 passed** in 121.15 s (Exit 0).
5. Output-Ordner `.hermes/opencode-output/2026-07-17_review2-fixes/`
   befüllt: STATUS.md, TASKS.md, DECISIONS.md, VERIFICATION.md, LOG.md.

### Dateien

Geändert: 11, Neu: 1 (docs/getting-started.md).
`git diff --stat`: +829 / −59 Zeilen.