# Plan: T-055 — `capabilities info <name>` + `capabilities server` zeigt description/schema

## Übersicht
Zwei Änderungen am `node-cli`:
1. `capabilities server` zeigt description und input_schema **immer** an (kein `--verbose`-Flag)
2. Neuer Subcommand `capabilities info <name>` für eine einzelne Capability mit Details

## 1. `capabilities server` zeigt description/schema immer an

**Datei:** `nodes/common/node_cli.py` — in `_cmd_capabilities_server()`

Aktuell wird nur `name`, `version`, `status`, `nodes` angezeigt. Erweitern um description und input_schema:

```python
for c in caps:
    name = c.get("name", "?")
    ver = c.get("version", "?")
    avail = c.get("available", False)
    nodes = c.get("nodes", [])
    status = "✅" if avail else "❌"
    node_names = ", ".join(
        n.get("node_name", n.get("node_id", "?")) for n in nodes
    ) if nodes else "(no nodes)"
    print(f"  {status} {name:20} v{ver:8}  [{node_names}]")
    desc = c.get("description")
    if desc:
        print(f"     {desc}")
    schema = c.get("input_schema")
    if schema:
        import json as _json
        print(f"     Input: {_json.dumps(schema, indent=6)}")
```

Das `--verbose`-Flag aus T-054 entfernen (Parser + Handler).

## 2. Neuer Subcommand `capabilities info <name>`

**Datei:** `nodes/common/node_cli.py`

### Parser
Im `capabilities`-Subparser einen neuen Subcommand `info` hinzufügen:

```python
p_info = p_caps_sub.add_parser("info", help="Show detailed info for a single capability.")
p_info.add_argument("name", help="Capability name to query.")
p_info.set_defaults(func=_cmd_capabilities_info)
```

### Handler
```python
def _cmd_capabilities_info(args: argparse.Namespace) -> int:
    _setup_logging(args.log_level)
    meta = load_meta()
    cfg = _effective_config()
    client = RelayClient(meta, cfg)
    try:
        resp = client._get(f"/relay/v2/discovery/capabilities/{args.name}")
        if resp.status_code == 404:
            print(f"Capability '{args.name}' not found.")
            return 1
        resp.raise_for_status()
        cap = resp.json()
    except Exception as exc:
        print(f"failed to query capability: {exc}", file=sys.stderr)
        return 1

    print(f"Name:        {cap.get('name', '?')}")
    print(f"Type:        {cap.get('type', '-')}")
    print(f"Version:     {cap.get('version', '?')}")
    print(f"Available:   {'yes' if cap.get('available', False) else 'no'}")
    desc = cap.get('description')
    if desc:
        print(f"Description: {desc}")
    schema = cap.get('input_schema')
    if schema:
        import json as _json
        print(f"Input Schema:")
        print(_json.dumps(schema, indent=2))
    nodes = cap.get('nodes', [])
    if nodes:
        print(f"\nNodes ({len(nodes)}):")
        for n in nodes:
            print(f"  - {n.get('node_name', n.get('node_id', '?'))} "
                  f"(load={n.get('load', 0):.1f}, "
                  f"queue={n.get('queue_depth', 0)})")
    return 0
```

Der Server-Endpoint `GET /discovery/capabilities/{name}` existiert bereits (DiscoveryDetailResponse).

## 3. Tests

**Datei:** `tests/nodes/test_node_cli.py`

Parser-Test für `capabilities info`:
```python
["capabilities", "info", "chat.ai"],
```

## 4. Doku

**Datei:** `docs/node/cli-reference.md`

`capabilities server`-Eintrag aktualisieren (zeigt jetzt description/schema). Neuen Eintrag für `capabilities info` hinzufügen.

## Reihenfolge
1. `_cmd_capabilities_server()` umbauen (description/schema immer anzeigen, `--verbose` entfernen)
2. `_cmd_capabilities_info()` hinzufügen
3. Parser anpassen (info + `--verbose` entfernen)
4. Tests
5. Doku
