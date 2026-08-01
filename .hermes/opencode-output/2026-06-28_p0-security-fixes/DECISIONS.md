# DECISIONS.md

## 2026-06-28: P0 Security Fixes (Audit-basiert)

**Entscheidung:** Vier kritische/high Findings aus dem Audit behoben:

- **C-1**: O(N) bcrypt-Scan -> deterministischer HMAC-SHA256-Lookup + Index + Single-bcrypt-Check. Neue Hilfsfunktion `compute_token_lookup(token)` mit server-seitigem Pepper (`settings.session_secret`). Neue DB-Spalte `node_tokens.token_lookup_hash` + Index `idx_node_tokens_lookup`. `validate_token` macht jetzt ein einziges indexed Query + einen bcrypt-Verify.
- **C-2**: Token-Akkumulation -> `login_with_master_seed` ruft jetzt `_replace_runtime_token` statt `_create_token` auf. Alte Runtime-Tokens des `__dashboard_admin__`-Nodes werden vor der Neuausstellung geloescht.
- **H-1**: `session_cookie_secure` -> default `True`.
- **H-2**: Admin-Node-RBAC-Bypass -> der Fallback-Pfad fuer Admin-Node-Tokens (ohne menschlichen User) ist jetzt auf die Whitelist `ADMIN_NODE_PERMISSIONS = {nodes:approve, nodes:token, nodes:delete, dashboard:view}` beschraenkt. Betroffen sind ausschliesslich Node-Management- und Dashboard-Lesezugriffe; `users:manage`, `groups:manage`, `tasks:admin`, `system:config` etc. sind fuer reine Node-Tokens gesperrt.

**Grund:** Audit (OpenCode, 2026-06-28) identifizierte 2 Critical + 4 High Findings.
Die P0-Fixes beseitigen den DoS-Vektor (C-1) und den RBAC-Bypass (H-2) vor
Produktionsbetrieb; C-2 verhindert Token-Leck; H-1 schuetzt Session-Cookies vor
MITM-Klartextuebertragung.

**Betroffene Files:** `auth.py`, `db.py`, `config.py`, `security.py`
**Betroffene Tasks:** T-028, T-029, T-030, T-031

---

## Abweichung vom Plan

Siehe `STATUS.md` Abschnitt "Abweichung vom Plan": In Task 3 (H-2) wurde in der
`ADMIN_NODE_PERMISSIONS`-Whitelist `dashboard:read` durch `dashboard:view`
ersetzt, da letzteres der im Codebase tatsaechlich verwendete Bezeichner fuer
die Dashboard-Lese-Permission ist. Semantisch aequivalent; andernfalls haetten
Admin-Node-Tokens das Dashboard verloren und mehrere Tests waeren fehlgeschlagen.
