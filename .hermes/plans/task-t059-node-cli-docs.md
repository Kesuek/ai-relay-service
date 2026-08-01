# Plan: T-059 — `node-cli docs` — Relay-Dokumentation über die CLI abrufen

## Problem
Headless Nodes (z.B. auf dem CT-Server) haben keinen Browser. Die Relay-Dokumentation ist nur über `GET /relay/v2/docs/` im Browser erreichbar. Ein Node-Operator müsste curl benutzen, um Docs zu lesen.

## Lösung
Neuer Subcommand `node-cli docs [<name>]`:
- Ohne Argument: `GET /relay/v2/docs/` → Liste aller verfügbaren Docs (Name + URL)
- Mit Argument: `GET /relay/v2/docs/{name}` → Inhalt der Doc-Seite als Markdown anzeigen

## Änderungen

### 1. Subcommand in `node_cli.py` registrieren
**Datei:** `nodes/common/node_cli.py`

Neuen Parser `p_docs` unter `p_sub` anlegen:
```python
p_docs = p_sub.add_parser("docs", help="Read relay documentation from the server.")
p_docs.add_argument("name", nargs="?", default=None, help="Document name (omit to list all)")
p_docs.set_defaults(func=_cmd_docs)
```

### 2. `_cmd_docs()` implementieren
```python
def _cmd_docs(self, args: argparse.Namespace) -> None:
    client = self._get_client()
    if args.name:
        # Einzelne Doc-Seite abrufen
        resp = client._get(f"/relay/v2/docs/{args.name}")
        data = resp.json()
        print(data.get("content", data.get("markdown", str(data))))
    else:
        # Alle Docs auflisten
        resp = client._get("/relay/v2/docs/")
        data = resp.json()
        docs = data if isinstance(data, list) else data.get("docs", [])
        print(f"Relay documentation ({len(docs)} pages):\n")
        for doc in docs:
            name = doc.get("name", doc.get("title", "?"))
            url = doc.get("url", "")
            print(f"  📄 {name}")
            if url:
                print(f"     {url}")
            print()
```

### 3. Tests
**Datei:** `tests/nodes/test_node_cli.py`

- `test_docs_list`: Ruft `node-cli docs` auf, prüft ob Liste angezeigt wird
- `test_docs_single`: Ruft `node-cli docs capabilities` auf, prüft ob Inhalt angezeigt wird
- `test_docs_not_found`: Ruft `node-cli docs nonexistent` auf, prüft Fehlermeldung

### 4. Doku
- `CHANGELOG.md` aktualisieren
- `docs/node/cli-reference.md` um `docs`-Befehl ergänzen

## Reihenfolge
1. `_cmd_docs()` + Parser in `node_cli.py`
2. Tests
3. Doku (CHANGELOG + cli-reference.md)
