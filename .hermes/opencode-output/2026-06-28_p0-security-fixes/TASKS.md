# TASKS.md — P0 Security Fixes

| ID    | Status | Notiz |
|-------|--------|-------|
| T-028 | ✅ done | C-2: Master-Seed-Token-Akkumulation (`_replace_runtime_token` statt `_create_token` in `login_with_master_seed`) |
| T-029 | ✅ done | H-1: `session_cookie_secure` default `True` |
| T-030 | ✅ done | H-2: Admin-Node-RBAC auf Node-Management + `dashboard:view` beschraenkt (`ADMIN_NODE_PERMISSIONS`) |
| T-031 | ✅ done | C-1: Deterministischer Token-Lookup (HMAC-SHA256 + Index + Single-bcrypt) |
