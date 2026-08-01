# Decisions

### 2026-07-17: GitHub Review Findings aus review-260717 behoben

- 11 Findings (2 CRITICAL, 2 HIGH, 4 MEDIUM, 3 LOW) aus dem GitHub-Review
  `review-260717` alle gefixt.
- **Reine Doku/Config-Änderungen** — kein Code berührt, keine API-Änderung.
- **Finding #1 (CRITICAL):** Clone-URL `github.com/felix/` → `github.com/Kesuek/`.
- **Finding #2 / #6 (CRITICAL/HIGH):** `relay-recovery`-Syntax in CHANGELOG
  und allen `docs/server/*.md` um `--db-path ~/.relay/server.db` ergänzt.
  README selbst enthielt den Befehl nicht; die docs/server-Dateien wurden
  stattdessen korrigiert.
- **Finding #3 / #7 (HIGH):** Token-Cleanup-Watchdog (`_token_cleanup_watchdog`
  in `main.py`, T-027) jetzt in `token-lifecycle.md`, `concepts.md`
  (Security-Abschnitt) und `STATUS.md` Phase 6 dokumentiert.
- **Finding #4 (HIGH):** Token-Typen-Tabelle in `token-lifecycle.md` um
  `adm_` (Master admin seed) und `bs_` (Bootstrap seed) ergänzt; Intro-Satz
  von "three credential types" auf "several credential families" korrigiert.
- **Finding #8 (HIGH):** `POST /relay/v2/discovery/worker-heartbeat` in
  `api.md` mit Payload-Beschreibung und Hinweis auf
  `replace_capabilities=True` dokumentiert.
- **Findings #5, #9, #10, #11 (MEDIUM/LOW):** README-Doc-Tabelle gekürzt,
  Python 3.11+-Requirement ergänzt, ruff-Lint/Format-Abschnitt ergänzt,
  Legacy-Doc-Liste als Mapping-Tabelle dargestellt.