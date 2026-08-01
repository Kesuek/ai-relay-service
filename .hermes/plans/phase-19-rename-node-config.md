# Plan: T-087 — Node-Konfiguration umbenennen

## Scope
- `capability_loader.py` → `node_config.py` (Code + Imports)
- `capabilities.active.yaml` → `node.yaml` (Pfadkonstanten + Disk)
- `capabilities.active.profile` → `node.profile` (Pfadkonstanten + Disk)
- `capabilities.d/` → `profiles.d/` (Pfadkonstanten + Disk)
- Schema: `capabilities` optional machen, Root `additionalProperties` erlauben
- Migration beim ersten Start: alte Dateien erkennen → nach neuem Namen kopieren
- `write_active_status()` auf Regex umbauen (YAML-Format bleibt erhalten)
- Doku + Tests + CLI-Referenzen aktualisieren

## Tasks (in Reihenfolge)

### 1. `node_config.py` — neues Modul, alter Inhalt
- **Aktion:** `git mv` `capability_loader.py` → `node_config.py`
- Kein Code-Change, nur Dateiname + Docstring + Modul-Doc anpassen
- `CAPABILITY_SCHEMA` → Schema lockern:
  - `required` entfernen (capabilities optional)
  - `additionalProperties: True` auf Root-Ebene
  - `"status"` bleibt als property (bereits vorhanden)
  - `"node_name"`, `"description"` als properties ergänzen
- Pfadkonstanten ändern:
  ```python
  PROFILES_DIR = Path(os.environ.get("RELAY_PROFILES_DIR", str(BASE_DIR / "profiles.d")))
  ACTIVE_PATH = BASE_DIR / "node.yaml"
  ACTIVE_PROFILE_NAME_PATH = BASE_DIR / "node.profile"
  ```
- `validate_profile()`: bei `capabilities` nicht vorhanden → leere Liste zurück, kein Fehler
- `write_active_status()` → regex-basiert (s.u.)
- Migration: `_migrate_old_paths()` prüft auf alte Dateien und kopiert sie

### 2. `write_active_status()` — Regex statt yaml.dump
```python
import re

_STATUS_RE = re.compile(r'^(status:\s*).*', re.MULTILINE)

def write_active_status(status: str | None) -> None:
    path = ACTIVE_PATH
    if not path.exists():
        return
    try:
        raw = path.read_text(encoding="utf-8")
        if status is None:
            # Remove status: line
            new_text = _STATUS_RE.sub("", raw)
            # Clean up double blank lines from removal
            new_text = re.sub(r'\n{3,}', '\n\n', new_text)
        else:
            if _STATUS_RE.search(raw):
                new_text = _STATUS_RE.sub(rf"\1{status}", raw)
            else:
                # Insert after first line (usually node_name or capabilities)
                first_newline = raw.index("\n") + 1 if "\n" in raw else len(raw)
                new_text = raw[:first_newline] + f"status: {status}\n" + raw[first_newline:]
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(new_text, encoding="utf-8")
        os.replace(tmp, path)
    except (OSError, yaml.YAMLError) as exc:
        log = __import__("logging").getLogger("relay.node_config")
        log.warning("could not write status to YAML: %s", exc)
```

### 3. Migration beim ersten Start (`_migrate_old_paths()`)
```python
def _migrate_old_paths() -> None:
    """Migrate old capability-named files to new node-named files.
    
    Called once at module import time. Detects old paths and copies
    them to the new locations. Old files are NOT deleted — they are
    left in place for backward compat during a rolling deploy.
    """
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    old_active = BASE_DIR / "capabilities.active.yaml"
    new_active = ACTIVE_PATH
    if old_active.exists() and not new_active.exists():
        shutil.copy2(old_active, new_active)
    old_profile = BASE_DIR / "capabilities.active.profile"
    new_profile = ACTIVE_PROFILE_NAME_PATH
    if old_profile.exists() and not new_profile.exists():
        shutil.copy2(old_profile, new_profile)
    old_profiles_dir = BASE_DIR / "capabilities.d"
    new_profiles_dir = PROFILES_DIR
    if old_profiles_dir.exists() and not new_profiles_dir.exists():
        shutil.copytree(old_profiles_dir, new_profiles_dir, dirs_exist_ok=True)
```

Aufruf am Ende des Moduls (nach Definition der Pfad-Konstanten):
```python
_migrate_old_paths()
```

### 4. `capability.py` — Docstring anpassen
- Verweis auf `capability_loader.py` → `node_config.py` ändern

### 5. `node_cli.py` — Imports + Pfade aktualisieren
- `from nodes.common.capability_loader import ...` → `from nodes.common.node_config import ...`
- `ACTIVE_PATH`, `PROFILES_DIR` usw. bleiben gleich (Name ändert sich nicht)
- CLI-Befehlsnamen bleiben (`capabilities publish`, etc.)

### 6. `node_daemon.py` — Import aktualisieren
- Gleiches Pattern wie node_cli.py

### 7. Test-Dateien
- `tests/nodes/test_capability_loader.py` → **umbenennen** → `tests/nodes/test_node_config.py`
- `test_route_registry.py`: Import von `capability_loader` → `node_config`
- `test_node_cli.py`: `from nodes.common import capability_loader as cl` → `from nodes.common import node_config as cl`
- `test_node_daemon.py`: gleiches Pattern
- Alle Pfade in Tests (`capabilities.active.yaml` → `node.yaml`, `capabilities.active.profile` → `node.profile`, `capabilities.d/` → `profiles.d/`) aktualisieren

### 8. Dokumentation
- `docs/node/cli-reference.md`:
  - `capabilities.active.yaml` → `node.yaml`
  - `capabilities.active.profile` → `node.profile`
  - `capabilities.d/` → `profiles.d/`
  - `RELAY_PROFILES_DIR` bleibt (nur Default-Wert ändert sich)
- `docs/node/capabilities.md`:
  - Gleiche Pfad-Updates
  - `capabilities` ist jetzt optional → Kapitel zur Node-Konfiguration ergänzen
- `docs/node/setup.md`:
  - `mkdir -p ~/.relay/capabilities.d` → `mkdir -p ~/.relay/profiles.d`
  - Pfade in Beispielen aktualisieren
- `docs/node/ssn.md`:
  - `~/.relay/capabilities.d/ssn.yaml` → `~/.relay/profiles.d/ssn.yaml`

### 9. `CHANGELOG.md` + `STATUS.md`
- CHANGELOG: Eintrag für T-087
- STATUS.md: Phase 19

## Nicht geändert
- `~/.relay/relay_config.json` (bleibt, ist Server-Konfiguration)
- CLI-Befehlsnamen: `capabilities publish/list/validate/...` bleiben
- `docs/reference/api.md` (keine API-Änderung)
- Server-seitiger Code (nur Node-seitig)

## Test-Validierung
- `pytest tests/nodes/test_node_config.py` (umbenannt) — alle bestanden
- `pytest tests/nodes/test_node_cli.py` — alle bestanden
- `pytest tests/nodes/test_node_daemon.py` — alle bestanden
- `pytest tests/test_route_registry.py` — alle bestanden
- Gesamte Suite läuft grün
