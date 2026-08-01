# Log

## 2026-07-17

- T-032: 11 GitHub-Review-Findings (review-260717) behoben
  - #1: README clone URL `felix` → `Kesuek`
  - #2/#6: `relay-recovery --db-path ~/.relay/server.db enable-recovery --all`
    in CHANGELOG + docs/server/{dashboard,admin,setup}.md
  - #3: Token-Cleanup-Watchdog-Abschnitt in token-lifecycle.md; Security-Note
    in concepts.md; T-027-Eintrag in STATUS.md Phase 6
  - #4: `adm_` (Master admin seed) + `bs_` (Bootstrap seed) in
    token-lifecycle.md-Token-Tabelle ergänzt
  - #5: reference-api-Beschreibung in README-Doc-Tabelle gekürzt
  - #8: worker-heartbeat-Endpoint in api.md mit Payload-Beschreibung +
    `replace_capabilities=True`-Hinweis
  - #9: "Requirements: Python 3.11+" Hinweis nach Quick-Start-Block
  - #10: ruff check / ruff format Abschnitte in README Tests
  - #11: Legacy-Doc-Liste als Mapping-Tabelle
- Tests: 203 passed (keine Regression)