# LOG.md — Abarbeitung P0 Security Fixes

**Start:** 2026-06-28
**Plan:** `.hermes/plans/2026-06-28_p0-security-fixes.md`

## Ablauf

1. **Kontext-Check:** Vor der ersten Aenderung wurden die im Plan genannten
   Code-Stellen gelesen und gegen den tatsaechlichen Stand abgeglichen
   (Zeilennummern, Funktions-Signaturen, Existenz von `_replace_runtime_token`,
   `validate_token`, DB-Migrationsmuster in `db.py`). Alle drei einfachen
   Stellen stimmten mit dem Plan ueberein.

2. **Task 1 (C-2):** In `src/relay_server/core/auth.py` den `_create_token`-
   Aufruf in `login_with_master_seed` durch `_replace_runtime_token` ersetzt.
   pytest: 162 passed.

3. **Task 2 (H-1):** In `src/relay_server/config.py` den Default von
   `session_cookie_secure` von `False` auf `True` gesetzt. pytest: 162 passed.

4. **Task 3 (H-2):** In `src/relay_server/api/v2/security.py` die Whitelist
   `ADMIN_NODE_PERMISSIONS` eingefuehrt und den Fallback-Zweig in
   `check_dashboard_permission` darauf beschraenkt. Vorab wurden alle
   `check_dashboard_permission(...)`-Aufrufe im Code geprueft, um sicherzugehen,
   dass keine Test-Pfade auf vom Admin-Node-Token bisher genutzte Permissions
   jenseits der Whitelist angewiesen sind.
   **Abweichung vom Plan:** Statt `dashboard:read` wurde `dashboard:view`
   verwendet, weil das der im Codebase tatsaechlich verwendete Bezeichner fuer
   die Dashboard-Lese-Permission ist (vgl. `dashboard.py:104`, `admin.py:18`,
   `db.py` default-seed `perm_dashboard`). Mit `dashboard:read` waeren Tests
   fehlgeschlagen. Siehe STATUS.md / DECISIONS.md. pytest: 162 passed.

5. **Task 4 (C-1):** Vier Teilschritte:
   - 4.1 `import hmac` ergaenzt; `_TOKEN_PEPPER`-Singleton + `_get_token_pepper()`
     + `compute_token_lookup(token)` in `auth.py` eingefuegt.
   - 4.2 Migration in `db.py::_run_migrations` ergaenzt: bedingtes
     `ALTER TABLE node_tokens ADD COLUMN token_lookup_hash` +
     `CREATE INDEX IF NOT EXISTS idx_node_tokens_lookup`.
   - 4.3 `_create_token` in `auth.py` berechnet `token_lookup_hash` und nimmt
     die Spalte ins INSERT auf.
   - 4.4 `validate_token` in `auth.py` umgebaut: ein indexed Query
     (`WHERE token_lookup_hash = ? AND (expires_at > ? OR expires_at IS NULL)`),
     danach ein einzelner `verify_secret`-Aufruf. Der bestehende
     Ablauf-Logik (expiry-Check, node_row laden, approved-Pruefung, result)
     bleibt erhalten.
   - 4.5 Schema-Verifikation via Python-One-Liner: Spalte + Index vorhanden,
     `compute_token_lookup` deterministisch und kollisionsfrei fuer
     unterschiedliche Tokens. pytest (mit `rm ~/.relay/server.db`): 162 passed.

## Endzustand

162 passed, 42 warnings. Kein Regressions- oder neu eingefuehrter Testfehler.
Die Test-Suite wurde nach Task 4 um ~26 s schneller (142.87 s -> 116.35 s),
was den Erfolg des deterministischen Lookups belegt.

## Output

- `STATUS.md`
- `TASKS.md`
- `DECISIONS.md`
- `VERIFICATION.md`
- `LOG.md` (diese Datei)
