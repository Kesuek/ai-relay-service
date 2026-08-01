# Decisions

### 2026-07-16: Phase 6 abgeschlossen

- **T-018:** `sys.exit(1)` in poller.py durch `FileNotFoundError`/`RuntimeError` ersetzt
- **T-019:** Alle `print()` in poller.py durch `logging` ersetzt
- **T-020:** CSRF Policy als Kommentar in dashboard.py dokumentiert
- **T-021:** `# type: ignore[misc]` in scheduler.py ergänzt
- **T-024:** `log_audit_event` redacted sensible Werte im `details`-Feld
- **T-025:** Master-Seed Dashboard-Session-TTL auf 1h verkürzt
- **T-026:** `node_capabilities`-Tabelle eingeführt, Migration für bestehende Daten, `claim_stage` nutzt neue Tabelle
- **T-027:** Synchroner DELETE aus `validate_token` entfernt, Background Cleaner in main.py
