# STATUS — Review 2026-07-17: 22 Findings behoben

**Datum:** 2026-07-17
**Plan:** `.hermes/plans/2026-07-17_review2-fixes.md`
**Review:** `review-20260717` (zweiter GitHub-Review)

## Ergebnis

Alle 22 Findings (4 CRITICAL, 15 MEDIUM, 3 LOW) abgearbeitet. 21 wurden
durchgefühert; Finding #2 (abgeschnittener Text in `design-board.md`) war
bereits im vorherigen Struktur-Commit `6a9c83e` korrekt angelegt — kein
`st[...]` mehr vorhanden, keine Aktion nötig.

Reine Doku-Änderung + 1 Zeile Code (docs-Whitelist für das neue
`getting-started.md`). Keine Geschäftslogik berührt. Tests grün
(203/203 passed).

## Geänderte Dateien

| Datei | Findings |
|-------|----------|
| `docs/server/admin.md` | #1 (Clone URL), #9 (Recovery-Ablauf) |
| `docs/reference/design-board.md` | #2 (bereits korrekt), #14 (db-node `.native`) |
| `docs/reference/api.md` | #3 + #12 (cURL/Payload/Error-Codes) |
| `docs/server/setup.md` | #4 (HTTPS/TLS), #5 (Database), #6 (Docker), #11 (Config-Ref), #13 (Token-Lifecycle), #15 (Troubleshooting server), #16 (Session-Secret-Rotation), #22 (Performance) |
| `docs/node/setup.md` | #7 (Console-Script), #15 (Troubleshooting node), #17 (Token-Storage-Security) |
| `docs/node/capabilities.md` | #8 (Handler-Fehlerbehandlung), #14 (Naming-Regel) |
| `docs/node/cli-reference.md` | #10 (Server-only Env-Vars) |
| `docs/concepts.md` | #14 (Naming-Regel), #19 (KI/AI), #21 (Glossar) |
| `docs/setup.md` | #20 (Entscheidungsbaum) |
| `docs/node-readme.md` | #20 (Entscheidungsbaum) |
| `docs/getting-started.md` | #18 (neu — 3 Szenarien + Decision Tree) |
| `src/relay_server/api/v2/docs.py` | #18 (Whitelist-Eintrag `getting-started`) |

## Abweichungen vom Plan

- **Task 2:** Der Plan erwartete ein `st[...]` in Zeile 5 von
  `design-board.md`. Die Datei wurde im Commit `6a9c83e` (erster Review)
  sauber neu angelegt; Zeile 5 ist vollständig
  ("…The relay core remains **KI-less**; it routes task stages and
  events, while board-specific persistence and logic live in dedicated
  nodes."). Keine Aktion nötig — als "bereits korrekt" dokumentiert.
- **Task 12:** mit Task 3 zusammengeführt (cURL-Beispiele im selben
  api.md-Abschnitt), wie im Plan vorgesehen.
- **Task 17 / Task 10:** Der Plan schlug eine `RELAY_RUNTIME_TOKEN`-Env-
  Var als Token-Storage-Alternative vor. Code-Prüfung zeigt: der Node-CLI
  liest das Token **nur** aus `~/.relay/ai-relay-agent.token`; die Env-Var
  wird zwar im Dashboard-HTML erwähnt, vom CLI aber nicht ausgewertet.
  Doku wurde entsprechend korrekt formuliert (Token-Datei + `chmod 600` +
  Bind-Mount / Secret-Manager-Provisionierung als Alternativen; Env-Var
  als "not yet honoured" markiert), statt eine nicht existierende Funktion
  zu dokumentieren.

## Verification

- `python -m pytest tests/ -q` → **203 passed** in 121.15 s (Exit 0)
- Docs-Whitelist-Test `test_public_docs_index` bestätigt das neue
  `getting-started`-Dokument im Index (Test bleibt grün).