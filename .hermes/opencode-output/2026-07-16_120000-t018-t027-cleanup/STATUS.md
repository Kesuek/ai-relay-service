# STATUS — T-018 bis T-027: Restliche Phase-6-Tasks

**Datum:** 2026-07-16
**Plan:** `.hermes/plans/2026-07-16_120000-t018-t027-cleanup.md`

## Ergebnis

Alle 8 Tasks umgesetzt. **Phase 6 abgeschlossen.**

## Commits

| Commit | Task | Beschreibung |
|--------|------|-------------|
| 2222f4b | T-018 + T-019 | `sys.exit(1)` → Exceptions; `print()` → `logging` in poller.py |
| 6430abb | T-020 | CSRF Policy Kommentar in dashboard.py |
| 7075245 | T-021 | `# type: ignore[misc]` in scheduler.py |
| 60bfca6 | T-024 | Secrets aus Audit-Logs redacted |
| f9e25f1 | T-025 | Master-Seed Session TTL auf 1h verkürzt |
| 06a8dc9 | T-026 | `node_capabilities`-Tabelle + Migration + Tests |
| 7ba5aaf | T-027 | DELETE aus validate_token entfernt, Background Cleaner in main.py |

## Abweichungen vom Plan

- T-026: `capability_type`-Filter in `claim_stage` wurde direkt über die neue Tabelle gelöst (SQL-Query statt JSON-Filter)
- T-027: Background Cleaner läuft stündlich (3600s) statt konfigurierbar
- T-021: Nur `scheduler.py` hatte tatsächlich fehlende Type-Ignore-Kommentare
