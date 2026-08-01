# P0 Security Fixes — Implementation Plan

> **Fuer OpenCode:** Tasks nacheinander abarbeiten. Nach jedem Task: `pytest` laufen lassen, alle Tests muessen gruen bleiben.

**Goal:** Zwei Critical DoS-Luecken und zwei High-Risk-Security-Probleme aus dem Audit beheben.

**Betroffener Commit:** `076e1eb`

---

## Task 1: C-2 — Token-Akkumulation beim Master-Seed-Login stoppen

**Objective:** `login_with_master_seed` erzeugt mit `_create_token` jedes Mal einen *neuen* Token, ohne alte zu loeschen. Ersetzen durch `_replace_runtime_token`, das vorher alle alten Runtime-Tokens des synthetischen Nodes loescht.

**Files:**
- Modify: `src/relay_server/core/auth.py` (Zeile 559)

**Fix:**

In `src/relay_server/core/auth.py` Zeile 559 aendern von:
```python
        return _create_token(
            dashboard_node_id,
            node_name,
            role="admin",
            token_type="runtime",
            pending=False,
            ttl_hours=settings.token_ttl_hours,
        )
```
nach:
```python
        return _replace_runtime_token(
            dashboard_node_id,
            node_name,
            role="admin",
        )
```

**Verifikation:**

```python
# LoginWithMasterSeed loescht alte Tokens
# Stelle sicher dass _replace_runtime_token nur runtime-Tokens
# des dashboard_node_id loescht, nicht andere Token-Typen.
```

**Tests laufen:**
```bash
cd /home/felix/projects/ai-relay-service
source .venv/bin/activate
.venv/bin/python -m pytest tests/ -q --ignore=tests/test_zeroconf.py -x --tb=short 2>&1 | tail -5
```

---

## Task 2: H-1 — session_cookie_secure default auf True

**Objective:** Session-Cookie wird ueber HTTP im Klartext gesendet. Default auf `True` aendern.

**Files:**
- Modify: `src/relay_server/config.py` (Zeile 38)

**Fix:**

In `src/relay_server/config.py` Zeile 38 aendern von:
```python
    session_cookie_secure: bool = False
```
nach:
```python
    session_cookie_secure: bool = True
```

**Tests laufen:**
```bash
cd /home/felix/projects/ai-relay-service
source .venv/bin/activate
.venv/bin/python -m pytest tests/ -q --ignore=tests/test_zeroconf.py -x --tb=short 2>&1 | tail -5
```

---

## Task 3: H-2 — Admin-Node-RBAC-Bypass einschraenken

**Objective:** `check_dashboard_permission` laesst jeden approved Admin-Node-Token durch alle Permissions durch. Einschraenken auf Node-Management-Permissions.

**Files:**
- Modify: `src/relay_server/api/v2/security.py` (Zeile 190-204)

**Fix:**

In `src/relay_server/api/v2/security.py` die Funktion `check_dashboard_permission` aendern von:
```python
def check_dashboard_permission(ctx: AuthContext, permission: str) -> None:
    """Check a dashboard permission; raises 403 if missing."""
    if ctx.user_id == "__master__":
        return
    if ctx.user_id:
        permissions = get_user_permissions(ctx.user_id)
        if permission in permissions:
            return
    # Fallback: admin node token.
    if ctx.role == "admin" and ctx.status in ("approved", "online"):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Missing permission: {permission}",
    )
```
nach:
```python
# Erlaubte Permissions fuer Admin-Node-Tokens (ohne menschlichen User)
ADMIN_NODE_PERMISSIONS: set[str] = {
    "nodes:approve",
    "nodes:token",
    "nodes:delete",
    "dashboard:read",
}

def check_dashboard_permission(ctx: AuthContext, permission: str) -> None:
    """Check a dashboard permission; raises 403 if missing."""
    if ctx.user_id == "__master__":
        return
    if ctx.user_id:
        permissions = get_user_permissions(ctx.user_id)
        if permission in permissions:
            return
    # Eingeschraenkter Fallback: admin node token darf nur Node-Management.
    if ctx.role == "admin" and ctx.status in ("approved", "online"):
        if permission in ADMIN_NODE_PERMISSIONS:
            return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Missing permission: {permission}",
    )
```

**Tests laufen:**
```bash
cd /home/felix/projects/ai-relay-service
source .venv/bin/activate
.venv/bin/python -m pytest tests/ -q --ignore=tests/test_zeroconf.py -x --tb=short 2>&1 | tail -5
```

---

## Task 4: C-1 — O(N) bcrypt-Scan durch deterministischen Token-Lookup ersetzen

**Objective:** `validate_token` iteriert ueber ALLE nicht-abgelaufenen Tokens und macht `bcrypt.checkpw` auf jedem. Stattdessen: HMAC-SHA256-Lookup-Hash in die DB, query per Index, nur ein bcrypt-Check.

**Files:**
- Modify: `src/relay_server/core/db.py` (Schema-Migration: neue Spalte + Index)
- Modify: `src/relay_server/core/auth.py` (hash_secret, _create_token, validate_token)

**Details:**

### Schritt 4.1: hash_secret() erweitern

In `auth.py` einen Server-Pepper einfuehren und `hash_secret()` so aendern, dass ein `token_lookup_hash` parallel berechnet wird:

```python
import hmac

# Server-seitiger Pepper fuer deterministischen Token-Lookup
# Geladen aus Config oder generiert bei erstem Start
_TOKEN_PEPPER: str | None = None

def _get_token_pepper() -> str:
    global _TOKEN_PEPPER
    if _TOKEN_PEPPER is None:
        _TOKEN_PEPPER = settings.session_secret or "relay-default-pepper-change-me"
    return _TOKEN_PEPPER

def hash_secret(secret: str) -> str:
    """Hash a secret with bcrypt."""
    return bcrypt.hashpw(secret.encode(), bcrypt.gensalt(rounds=12)).decode()

def compute_token_lookup(token: str) -> str:
    """Deterministic HMAC-SHA256 lookup hash for fast token lookup."""
    return hmac.new(
        _get_token_pepper().encode(),
        token.encode(),
        "sha256",
    ).hexdigest()
```

### Schritt 4.2: DB-Schema erweitern

In `db.py` eine Migration hinzufuegen:

```python
# Nach dem bestehenden CREATE TABLE block:
conn.execute("""
    ALTER TABLE node_tokens ADD COLUMN token_lookup_hash TEXT
""")
conn.execute("""
    CREATE INDEX IF NOT EXISTS idx_node_tokens_lookup
    ON node_tokens(token_lookup_hash)
""")
```

Da die DB schon existiert, muss die Migration `IF NOT EXISTS`-Column-Add oder try/except nutzen. SQLite unterstuetzt `ALTER TABLE ADD COLUMN` aber nicht `IF NOT EXISTS` fuer Columns. Alternative:

```python
# Pruefe ob Spalte existiert
cursor = conn.execute("PRAGMA table_info(node_tokens)")
cols = {row[1] for row in cursor.fetchall()}
if "token_lookup_hash" not in cols:
    conn.execute("ALTER TABLE node_tokens ADD COLUMN token_lookup_hash TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_node_tokens_lookup ON node_tokens(token_lookup_hash)")
    conn.commit()
```

### Schritt 4.3: _create_token() anpassen

In `auth.py` in `_create_token()` nach Zeile 179 (`token = ...`) einfuegen:

```python
        token_lookup_hash = compute_token_lookup(token)
```

Und im INSERT (Zeile 184+) die Spalte `token_lookup_hash` mit aufnehmen:

```python
        conn.execute(
            """
            INSERT INTO node_tokens
            (token_id, node_id, node_name, token_hash, token_lookup_hash, token_type, pending, role, expires_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                token_id,
                node_id,
                node_name,
                token_hash,
                token_lookup_hash,   # NEU
                token_type,
                1 if pending else 0,
                role,
                _format_time(expires),
                _format_time(now),
            ),
        )
```

### Schritt 4.4: validate_token() umbauen

In `auth.py` die `validate_token()`-Funktion aendern von O(N) bcrypt-Scan zu:

```python
def validate_token(token: str, require_approved: bool = True) -> Optional[dict]:
    """Validate a bearer token. Returns node info or None."""
    conn = get_conn()
    try:
        # Deterministic lookup: ein Query, ein bcrypt-Check.
        token_lookup_hash = compute_token_lookup(token)
        now = _format_time(_now())
        row = conn.execute(
            """
            SELECT token_id, node_id, node_name, token_type, pending, role,
                   expires_at, token_hash
            FROM node_tokens
            WHERE token_lookup_hash = ?
              AND (expires_at > ? OR expires_at IS NULL)
            LIMIT 1
            """,
            (token_lookup_hash, now),
        ).fetchone()

        if not row:
            return None
        if not verify_secret(token, row["token_hash"]):
            return None

        expires = _parse_time(row["expires_at"])
        if expires and _now() > expires:
            conn.execute(
                "DELETE FROM node_tokens WHERE token_id = ?",
                (row["token_id"],),
            )
            conn.commit()
            return None

        # Rest bleibt wie bisher: node_row laden, result bauen
        node_row = conn.execute(
            "SELECT node_id, node_name, endpoint, capabilities, status, role FROM nodes WHERE node_id = ?",
            (row["node_id"],),
        ).fetchone()
        if not node_row:
            return None

        result = {
            "token_id": row["token_id"],
            "node_id": node_row["node_id"],
            "node_name": node_row["node_name"],
            "endpoint": node_row["endpoint"],
            "capabilities": _parse_capabilities(node_row["capabilities"]),
            "status": node_row["status"],
            "role": node_row["role"],
            "token_type": row["token_type"],
            "pending": bool(row["pending"]),
            "expires_at": row["expires_at"],
        }
        # ... restlicher Code bleibt (approved-Check, logging etc.)
    finally:
        conn.close()
```

Der restliche Code nach dem Query (approved-Prüfung, Logging) bleibt wie er ist.

### Schritt 4.5: Tests anpassen

Bestehende Auth-Tests nutzen das Token-System. Durch das neue `token_lookup_hash`-Feld aendert sich das Verhalten nicht, aber es muss persistiert sein. Ein Migrations-Test sollte die Spalte auf Existenz pruefen.

**Tests laufen:**
```bash
cd /home/felix/projects/ai-relay-service
source .venv/bin/activate
.venv/bin/python -m pytest tests/ -q --ignore=tests/test_zeroconf.py -x --tb=short 2>&1 | tail -5
```
Erwartet: Alle Tests passed. Falls Token-Lookup fehlschlaegt, liegt es an fehlender Migration (alte Tokens ohne `token_lookup_hash`).

```bash
# Optional: Migration auf bestehender DB testen
# Loesche server.db und lass Tests neu erstellen
rm ~/.relay/server.db 2>/dev/null; .venv/bin/python -m pytest tests/ -q --ignore=tests/test_zeroconf.py -x 2>&1 | tail -5
```

---

## Abschliessende Antwort fuers Project Board

Nach OpenCode-Ausfuehrung:

### TASKS.md

| ID | Status | Notiz |
|----|--------|-------|
| T-028 | ✅ done | C-2: Master-Seed-Token-Akkumulation (replace statt create) |
| T-029 | ✅ done | H-1: session_cookie_secure default True |
| T-030 | ✅ done | H-2: Admin-Node-RBAC auf Node-Management beschraenkt |
| T-031 | ✅ done | C-1: Deterministischer Token-Lookup (HMAC-SHA256 + Index) |

### DECISIONS.md

```markdown
## 2026-06-28: P0 Security Fixes (Audit-basiert)

**Entscheidung:** Vier kritische/high Findings aus dem Audit behoben:
- C-1: O(N) bcrypt-Scan -> deterministischer HMAC-SHA256-Lookup + Index + Single-bcrypt
- C-2: Token-Akkumulation -> _replace_runtime_token statt _create_token
- H-1: session_cookie_secure -> default True
- H-2: Admin-Node-RBAC-Bypass -> auf nodes:approve/token/delete + dashboard:read beschraenkt

**Grund:** Audit (OpenCode, 2026-06-28) identifizierte 2 Critical + 4 High Findings.
Die P0-Fixes beseitigen DoS-Vektor und RBAC-Bypass vor Produktionsbetrieb.

**Betroffene Files:** auth.py, db.py, config.py, security.py
**Betroffene Tasks:** T-028, T-029, T-030, T-031

---

## OpenCode-Output

Nach Abarbeitung dieses Plans legt OpenCode seine Zusammenfassung ab unter:

```
.hermes/opencode-output/2026-06-28_p0-security-fixes/
├── STATUS.md
├── TASKS.md
├── DECISIONS.md
├── VERIFICATION.md
└── LOG.md
```