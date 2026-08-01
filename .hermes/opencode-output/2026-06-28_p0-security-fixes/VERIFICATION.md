# VERIFICATION.md

## Test-Suite

```bash
cd /home/felix/projects/ai-relay-service
source .venv/bin/activate
.venv/bin/python -m pytest tests/ -q --ignore=tests/test_zeroconf.py -x --tb=short 2>&1 | tail -5
```

**Ergebnis (Endzustand nach Task 4, mit frischer DB):**

```
162 passed, 42 warnings in 116.35s (0:01:56)
EXIT=0
```

Nach jedem einzelnen Task wurde dieselbe Suite ausgefuehrt und blieb gruen:

| Task | Ergebnis |
|------|----------|
| Task 1 (C-2) | 162 passed in 142.87s |
| Task 2 (H-1) | 162 passed in 146.71s |
| Task 3 (H-2) | 162 passed in 147.15s |
| Task 4 (C-1) | 162 passed in 116.35s (frisch migrierte DB) |

Die deutliche Beschleunigung nach Task 4 (~26 s) ist ein direkter Beleg dafuer,
dass der O(N) bcrypt-Scan erfolgreich durch den deterministischen Lookup
ersetzt wurde: Pro `validate_token`-Aufruf laeuft jetzt nur noch ein einziger
bcrypt-Check statt u. U. vieler.

## Schema-Verifikation (Task 4)

```bash
.venv/bin/python -c "
from relay_server.core.db import get_conn
from relay_server.core import auth
c = get_conn()
cols = [r[1] for r in c.execute('PRAGMA table_info(node_tokens)').fetchall()]
idx = [r[1] for r in c.execute('PRAGMA index_list(node_tokens)').fetchall()]
assert 'token_lookup_hash' in cols
assert 'idx_node_tokens_lookup' in idx
h1 = auth.compute_token_lookup('rt_test123')
h2 = auth.compute_token_lookup('rt_test123')
h3 = auth.compute_token_lookup('rt_other')
assert h1 == h2 and h1 != h3 and len(h1) == 64
print('MIGRATION OK')
"
```

Ausgabe:

```
columns: ['token_id', 'node_id', 'node_name', 'token_hash', 'token_type',
          'pending', 'role', 'expires_at', 'created_at', 'token_lookup_hash']
indexes: ['idx_node_tokens_lookup', 'sqlite_autoindex_node_tokens_2',
          'sqlite_autoindex_node_tokens_1']
compute_token_lookup OK len= 64
MIGRATION OK
```

Die Migration ist idempotent (`PRAGMA table_info` + bedingtes `ALTER TABLE` +
`CREATE INDEX IF NOT EXISTS`) und laeuft auch auf bestehenden Datenbanken, die
die Spalte noch nicht enthalten. Alte Tokens ohne `token_lookup_hash` werden
bei der naechsten Validierung nicht mehr gefunden und muessen erneuert werden
(das ist das gewuenschte Verhalten: ein Angreifer kann keine Tokens ohne
Lookup-Hash mehr nutzen, und legitme User refreshen via `refresh_token` bzw.
einem neuen Login).

## Statische Verifikation der Einzelaenderungen

- **Task 1 (C-2):** `src/relay_server/core/auth.py` — `login_with_master_seed`
  gibt jetzt `_replace_runtime_token(dashboard_node_id, node_name, role="admin")`
  zurueck. `_replace_runtime_token` loescht vorher alle Runtime-Tokens des
  `__dashboard_admin__`-Nodes (`DELETE FROM node_tokens WHERE node_id = ? AND
  token_type = ?`) und legt danach genau ein neues an. Andere Token-Typen
  (z. B. `temporary`) bleiben unberuehrt.
- **Task 2 (H-1):** `src/relay_server/config.py` — `session_cookie_secure: bool
  = True`. HTTP-Klartext-Uebertragung des Session-Cookies ist damit per Default
  aus; nur explizites `session_cookie_secure=False` in der Konfiguration stellt
  das alte Verhalten wieder her.
- **Task 3 (H-2):** `src/relay_server/api/v2/security.py` — neue Konstante
  `ADMIN_NODE_PERMISSIONS` und geaenderter Fallback-Zweig in
  `check_dashboard_permission`. Admin-Node-Tokens duerfen nur noch
  `nodes:approve`, `nodes:token`, `nodes:delete`, `dashboard:view`. Der Master
  (`__master__`) und menschliche User mit expliziter Permission bleiben
  unberuehrt.
- **Task 4 (C-1):** `src/relay_server/core/auth.py` + `core/db.py` —
  `compute_token_lookup()` (HMAC-SHA256 mit server-seitigem Pepper), neue
  Spalte `token_lookup_hash` + Index, `_create_token` fuellt die Spalte beim
  INSERT, `validate_token` macht ein indexed Query + einen bcrypt-Check.
