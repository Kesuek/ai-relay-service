# STATUS — GitHub Review Findings: 11 Dokumentations-Fehler

**Datum:** 2026-07-17
**Plan:** `.hermes/plans/2026-07-17_review-fixes.md`
**Review:** `review-260717`

## Ergebnis

Alle 11 Findings (2 CRITICAL, 2 HIGH, 4 MEDIUM, 3 LOW) behoben. Reine
Markdown/Config-Änderungen — kein Code berührt. Tests grün (203/203 passed).

## Geänderte Dateien

| Datei | Findings |
|-------|----------|
| `README.md` | #1 (clone URL), #5 (doc table), #9 (Python 3.11+), #10 (ruff), #11 (legacy mapping) |
| `CHANGELOG.md` | #6 (relay-recovery `--db-path`) |
| `STATUS.md` | #3 / #7 (T-027 Watchdog in Phase 6) |
| `docs/node/token-lifecycle.md` | #3 (cleanup section), #4 (adm_/bs_ token types) |
| `docs/concepts.md` | #3 (watchdog note in security model) |
| `docs/reference/api.md` | #8 (worker-heartbeat payload description) |
| `docs/server/dashboard.md` | #2 (relay-recovery `--db-path`) |
| `docs/server/admin.md` | #2 (relay-recovery `--db-path`) |
| `docs/server/setup.md` | #2 (relay-recovery `--db-path`) |

## Abweichungen vom Plan

- **Task 2:** Der Plan nannte `README.md` Quick Start + Recovery section für
  den relay-recovery-Fix, aber README enthält keine `relay-recovery`-Befehle
  (nur `relay-server admin init-master`, der `--db-path` nicht benötigt). Der
  gleiche Syntaxfehler bestand jedoch in `docs/server/{dashboard,admin,setup}.md`
  — diese wurden konsistent korrigiert, so dass der Finding-Inhalt vollständig
  abgedeckt ist.
- **Task 7:** T-027 war bereits in Phase 6 gelistet als
  `validate_token synchroner DELETE (T-027)`. Umbenannt in
  `validate_token synchroner DELETE → Token-Cleanup-Watchdog (T-027)`, damit
  die Lösung (nicht nur das Problem) sichtbar ist.

## Verification

- `python -m pytest tests/ -q` → **203 passed** in 125.16s (Exit 0)