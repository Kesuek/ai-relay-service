# Plan: T-062 — node-cli Update-Check + Update-Apply

## Ziel
Zwei neue Subcommands für `node-cli`:
- `node-cli update check` — prüft via `git fetch` + Commit-Vergleich ob ein Update auf GitHub verfügbar ist
- `node-cli update apply` — führt `git pull` + Service-Restart aus

Ermöglicht Updates ohne manuelles SSH auf jeden Node.

## Änderungen

### 1. `nodes/common/node_utils.py` — `get_repo_info()` + `check_for_updates()`
```python
REPO_DIR = Path.home() / "projects" / "ai-relay-service"

def get_repo_info() -> dict:
    """Returns {local_commit, local_branch, remote_commit, behind_count, has_upstream}."""
    # git rev-parse HEAD → local_commit
    # git rev-parse --abbrev-ref HEAD → local_branch
    # git rev-parse @{upstream} → remote_commit (falls upstream existiert)
    # git rev-list --count HEAD..@{upstream} → behind_count

def check_for_updates() -> dict:
    """Führt git fetch aus und gibt get_repo_info() zurück."""
    # git fetch origin
    # return get_repo_info()

def apply_update() -> dict:
    """Führt git pull + Service-Restart aus.
    Returns {success, message, before_commit, after_commit}."""
    # before = get_repo_info()
    # git pull
    # after = get_repo_info()
    # systemctl --user restart ai-relay-node-cli.service
    # return {success, message, before, after}
```

### 2. `nodes/common/node_cli.py` — Subcommands `update check` + `update apply`
- `_cmd_update_check(args)` → ruft `check_for_updates()` auf, zeigt Ergebnis an
- `_cmd_update_apply(args)` → ruft `apply_update()` auf, zeigt Ergebnis an
- In `_build_parser()`: `p_update = sub.add_parser("update", ...)` mit Subparsern `check` und `apply`

### 3. Tests
**`tests/nodes/test_node_cli.py`:**
- `test_update_check_no_updates()` — mockt git fetch, prüft Ausgabe
- `test_update_check_with_updates()` — mockt behind_count > 0
- `test_update_apply()` — mockt git pull + restart
- `test_update_apply_no_upstream()` — kein upstream konfiguriert

## Reihenfolge
1. `node_utils.py` — `get_repo_info()`, `check_for_updates()`, `apply_update()`
2. `node_cli.py` — Subcommands + Parser
3. Tests
4. `pytest` — alle Tests grün
