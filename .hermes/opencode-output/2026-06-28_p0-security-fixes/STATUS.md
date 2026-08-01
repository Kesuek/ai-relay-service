# STATUS — P0 Security Fixes

**Datum:** 2026-06-28
**Betroffener Commit:** `076e1eb`
**Plan:** `.hermes/plans/2026-06-28_p0-security-fixes.md`

## Zusammenfassung

Alle vier P0-Findings aus dem Security-Audit wurden umgesetzt. Nach jedem Task
wurde die Test-Suite ausgefuehrt; alle 162 Tests blieben gruen.

| Task | Finding | Status | Notiz |
|------|---------|--------|-------|
| Task 1 | C-2 Token-Akkumulation beim Master-Seed-Login | ✅ done | `_create_token` -> `_replace_runtime_token` in `auth.py` |
| Task 2 | H-1 `session_cookie_secure` default False | ✅ done | Default auf `True` in `config.py` |
| Task 3 | H-2 Admin-Node-RBAC-Bypass | ✅ done | `ADMIN_NODE_PERMISSIONS` Whitelist in `security.py` |
| Task 4 | C-1 O(N) bcrypt-Scan | ✅ done | HMAC-SHA256-Lookup + Migration + Index in `auth.py`/`db.py` |

## Betroffene Dateien

- `src/relay_server/core/auth.py`
- `src/relay_server/core/db.py`
- `src/relay_server/config.py`
- `src/relay_server/api/v2/security.py`

## Verifikation

Siehe `VERIFICATION.md`. Test-Suite: 162 passed.

## Abweichung vom Plan

**Task 3 (H-2):** Der Plan nennt in der `ADMIN_NODE_PERMISSIONS`-Whitelist
die Permission `dashboard:read`. Im Codebase wird die Lese-Permission fuer das
Dashboard jedoch als `dashboard:view` verwendet (vgl. `api/v2/dashboard.py:104`
und `api/v2/admin.py:18`, sowie der default permission-seed in
`db.py:277` `perm_dashboard` -> `dashboard:view`).

Mit `dashboard:read` waere Admin-Node-Tokens das Dashboard entzogen worden und
Tests waieren fehlgeschlagen (`test_auth.py`, `test_scheduler.py`, u.a. nutzen
den Admin-Node-Token via Bearer gegen `/relay/v2/admin/nodes`, das
`dashboard:view` verlangt).

Eingesetzte Whitelist (semantisch aequivalent zum Plan, aber mit dem
tatsaechlich im Code verwendeten Bezeichner):

```python
ADMIN_NODE_PERMISSIONS: set[str] = {
    "nodes:approve",
    "nodes:token",
    "nodes:delete",
    "dashboard:view",   # Plan: "dashboard:read"  -> siehe Abweichung oben
}
```

Alle weiteren Aenderungen entsprechen 1:1 dem Plan.
