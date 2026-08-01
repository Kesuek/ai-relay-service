# STATUS — HIGH Security & Reliability Fixes

**Datum:** 2026-07-10
**Betroffene Commits:** `d4ac1ec`, `4d9e303`, `53a7884`
**Plan:** `.hermes/plans/2026-07-10_high-security-fixes.md`

## Zusammenfassung

Alle drei HIGH-Findings aus dem GitHub-Code-Review wurden umgesetzt.
Nach jedem Task wurde die jeweilige Test-Suite ausgefuehrt; alle Tests blieben
gruen. Die erweiterte Suite (57 Tests ueber discovery, events, dashboard, auth)
wurde am Ende erneut ausgefuehrt.

| Task | Finding | Status | Notiz |
|------|---------|--------|-------|
| Task 1 | Heartbeat Race Condition (TOCTOU) | done | `mark_offline_nodes()` re-prueft `last_seen` in UPDATE-WHERE-Klausel |
| Task 2 | Fehlendes Audit Logging | done | `audit_logs`-Tabelle + `log_audit_event()` in approve, token, delete |
| Task 3 | EventBus Silent Drops | done | `X-Dropped`-Header im SSE-Stream + `subscriber_lagging`-Warn-Event bei 100 Drops |

## Betroffene Dateien

- `src/relay_server/core/discovery.py`
- `src/relay_server/core/db.py`
- `src/relay_server/core/events.py`
- `src/relay_server/api/v2/admin.py`

## Verifikation

Siehe `VERIFICATION.md`. Test-Suite: 57 passed (discovery + events + dashboard + auth).

## Abweichung vom Plan

Keine inhaltlichen Abweichungen. Die `test_discovery.py`-Tests benoetigen
`RELAY_SESSION_SECRET` (>= 32 Zeichen) als Env-Variable, da der vorige
CRITICAL-Fix (T-012) den Token-Pepper fail-fast gemacht hat. Diese Env-Variable
wurde beim Test-Run gesetzt (`RELAY_SESSION_SECRET="test-session-secret-do-not-use-in-production"`),
entsprechend der bereits in anderen Test-Dateien (`test_auth.py`, `test_scheduler.py`,
`test_dashboard.py`) etablierten Praxis. Dies ist kein neu eingefuehrtes Problem,
sondern ein vorgegebenes Test-Setup — die Tests schlagen auch ohne diese Aenderungen
fehl, wenn das Secret fehlt.