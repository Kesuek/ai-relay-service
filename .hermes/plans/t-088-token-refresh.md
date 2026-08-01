# Plan: T-088 Token-Refresh-Robustheit

## Ziel
Node-Daemon und CLI refreshen Runtime-Token proaktiv, bevor er abläuft. Kein dauerhafter Verbindungsverlust mehr.

## Änderungen

### 1. `nodes/common/node_utils.py` — `save_token()`/`load_token()` auf JSON umstellen (T-088a)

**Aktuell:** `save_token(token: str)` schreibt Plaintext, `load_token()` gibt `str | None` zurück.

**Neu:** `save_token(token: str, expires_at: str | None = None)` schreibt JSON:
```json
{"token": "rt_...", "expires_at": "2026-08-08T08:30:00+00:00"}
```
`load_token()` gibt `dict | None` zurück mit `{"token": "...", "expires_at": "..."}`.

**Migration:** `load_token()` muss alten Plaintext erkennen (kein JSON) und in neues Format konvertieren.

**Betroffene Aufrufer anpassen:**
- `node_cli.py:174` — `self.token = load_token()` → `data = load_token(); self.token = data["token"] if data else None; self.token_expires_at = data.get("expires_at") if data else None`
- `node_cli.py:238` — `save_token(new)` → `save_token(new, expires_at=...)`
- `node_cli.py:260` — `save_token(new)` → `save_token(new, expires_at=...)`
- `ssn_proxy.py:63` — `return token_path.read_text().strip()` → `return json.loads(token_path.read_text())["token"]`
- `node_daemon.py:350` — `"RELAY_TOKEN_FILE": str(TOKEN_PATH)` bleibt (wird vom Handler gelesen, der Handler liest Plaintext → muss auch JSON verstehen oder wir lassen den Env-Var auf den Token-Wert zeigen)

### 2. `nodes/common/node_cli.py` — `_refresh_token()` speichert `expires_at` (T-088b)

In `_refresh_token()` (Z. 227-243):
```python
if r.status_code == 200:
    data = r.json()
    new = data.get("token")
    expires_at = data.get("expires_at")
    if new:
        save_token(new, expires_at=expires_at)
        self.token = new
        self.token_expires_at = expires_at
        return True
```

Gleiches in `_recover_runtime_token()` (Z. 245-265):
```python
new = data.get("token")
expires_at = data.get("expires_at")
if new:
    save_token(new, expires_at=expires_at)
    self.token = new
    self.token_expires_at = expires_at
return new
```

`RelayClient.__init__` (Z. 170-182) muss `self.token_expires_at` initialisieren:
```python
self.token = load_token()
if self.token:
    self.token = data["token"]
    self.token_expires_at = data.get("expires_at")
```

### 3. `nodes/common/node_cli.py` — Proaktiver Refresh im Heartbeat-Loop (T-088c)

In `_heartbeat_loop()` (Z. 607-629), **vor** dem Heartbeat-Aufruf:
```python
# Proaktiver Token-Refresh: wenn Token in <1h abläuft, vorher refreshen
if self.client.token_expires_at:
    try:
        exp = datetime.fromisoformat(self.client.token_expires_at)
        if exp - datetime.now(timezone.utc) < timedelta(hours=1):
            log.info("token expires soon (%s), refreshing proactively", self.client.token_expires_at)
            self.client._refresh_token()
    except (ValueError, TypeError):
        pass
```

`timedelta` und `timezone` in den Import (Z. 48) aufnehmen.

### 4. `nodes/common/node_cli.py` — CLI-Subcommands: `_get()` → `_get_with_retry()` (T-088d)

Vier Stellen:

| Subcommand | Zeile | Aktuell | Neu |
|-----------|-------|---------|-----|
| `_cmd_capabilities_server` | 1435 | `client._get(...)` | `client._get_with_retry(...)` |
| `_cmd_capabilities_info` | 1475 | `client._get(...)` | `client._get_with_retry(...)` |
| `_cmd_node_list` | 1515 | `client._get(...)` | `client._get_with_retry(...)` |
| `_cmd_node_info` | 1558, 1571 | `client._get(...)` | `client._get_with_retry(...)` |

### 5. `src/relay_server/config.py` — `registration_secret_ttl_hours` anheben (T-088e)

Zeile 38: `registration_secret_ttl_hours: int = 12` → `registration_secret_ttl_hours: int = 168`

### 6. Tests

- `test_node_utils.py` — `test_save_load_token_json_format()`: speichert mit `expires_at`, lädt, prüft Token + expires_at
- `test_node_utils.py` — `test_load_token_legacy_plaintext()`: alter Plaintext wird erkannt und konvertiert
- `test_node_cli.py` — `test_token_refresh_saves_expires_at()`: Mock-Response mit `expires_at`, prüft dass `save_token` mit `expires_at` aufgerufen wird
- `test_node_cli.py` — `test_proactive_refresh_before_expiry()`: Token läuft in 30min ab → prüft dass `_refresh_token` aufgerufen wird
- `test_node_cli.py` — `test_proactive_refresh_skipped_when_fresh()`: Token läuft in 2d ab → prüft dass `_refresh_token` NICHT aufgerufen wird

### 7. Dokumentation

- `CHANGELOG.md` — Eintrag für T-088a–T-088e
- `docs/node/cli-reference.md` — ggf. Hinweis auf proaktiven Refresh

## Reihenfolge

1. `node_utils.py` — `save_token`/`load_token` auf JSON umstellen
2. `node_cli.py` — `RelayClient` an neues Token-Format anpassen
3. `node_cli.py` — `_refresh_token`/`_recover_runtime_token` speichern `expires_at`
4. `node_cli.py` — Proaktiver Refresh im Heartbeat-Loop
5. `node_cli.py` — CLI-Subcommands: `_get()` → `_get_with_retry()`
6. `ssn_proxy.py` — Token-Loading anpassen
7. `config.py` — `registration_secret_ttl_hours` auf 168
8. Tests schreiben
9. Doku aktualisieren
10. `pytest` laufen lassen
