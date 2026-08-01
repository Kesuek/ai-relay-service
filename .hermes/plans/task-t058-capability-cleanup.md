# Plan: T-058 — Capability-Cleanup für nicht geheartbeatete Capabilities

## Problem
`vault` und `image.generate.ai` auf dem Mac wurden bei der Node-Registrierung in die `nodes.capabilities` JSON-Spalte geschrieben. Der Mac heartbeatet aber nur seine aktiven Capabilities. Da `replace_capabilities=True` im Heartbeat die JSON-Spalte ersetzt, müssten die alten Einträge eigentlich verschwinden. Tun sie aber nicht — sie tauchen weiter in `get_capabilities()` auf.

## Ursache
`get_capabilities()` in `discovery.py` liest die `nodes.capabilities` JSON-Spalte. Wenn der Mac heartbeatet, wird die Spalte mit `replace_capabilities=True` überschrieben — aber nur wenn der Heartbeat `capabilities` im Body mitsendet. Der Mac heartbeatet über den `worker-heartbeat` Endpoint, der `capabilities` mitsendet. Trotzdem bleiben alte Einträge.

Mögliche Ursachen:
1. Der Mac heartbeatet nicht mit `replace_capabilities=True` (sondern merged)
2. Der `worker-heartbeat` Endpoint hat einen Bug
3. Die `nodes.capabilities` JSON-Spalte wird nicht korrekt aktualisiert

## Lösung

### 1. `get_capabilities()` filtert Nodes mit veraltetem last_seen
**Datei:** `src/relay_server/core/discovery.py` — in `get_capabilities()`

Bereits vorhanden: Die Query filtert `WHERE last_seen > ? OR available = 0`. Das ist korrekt — Nodes die nicht mehr heartbeaten werden ausgefiltert. Aber die Capabilities von aktiven Nodes die nie geheartbeatet wurden bleiben.

### 2. `sync_node_capabilities()` beim Heartbeat löscht alte Einträge
**Datei:** `src/relay_server/core/db.py` — in `sync_node_capabilities()`

Bereits vorhanden: `DELETE FROM node_capabilities WHERE node_id = ?` am Anfang. Das ist korrekt.

### 3. Heartbeat aktualisiert die JSON-Spalte korrekt
**Datei:** `src/relay_server/core/discovery.py` — in `heartbeat()`

Prüfen ob `replace_capabilities=True` korrekt die JSON-Spalte ersetzt. Der Code in Zeile 87-92 macht das bereits:
```python
if replace_capabilities:
    updates.append("capabilities = ?")
    params.append(_serialize_capabilities(capabilities))
    merged = capabilities
```

### 4. Zusätzlich: Admin-Endpoint zum manuellen Cleanup
**Datei:** `src/relay_server/api/v2/admin.py`

Neuer Endpoint `POST /admin/nodes/{node_id}/sync-capabilities` der `sync_node_capabilities()` für einen Node aufruft und die JSON-Spalte aus den Heartbeat-Daten neu aufbaut.

### 5. Oder einfacher: `get_capabilities()` merged nur Capabilities die per Heartbeat bestätigt wurden
**Datei:** `src/relay_server/core/discovery.py` — in `get_capabilities()`

Statt aus der `nodes.capabilities` JSON-Spalte zu lesen, aus der `node_capabilities` Tabelle lesen (die nur per Heartbeat befüllt wird). Das ist der sauberste Fix.

## Änderungen

### 1. `get_capabilities()` liest aus `node_capabilities` statt `nodes.capabilities`
**Datei:** `src/relay_server/core/discovery.py`

Aktuell:
```python
caps = _parse_capabilities(row["capabilities"])
```

Neu: Capability-Namen aus `node_capabilities` für den Node laden, dann Details aus der JSON-Spalte (oder direkt aus `node_capabilities`).

Einfacher: Die `node_capabilities` Tabelle hat bereits `capability_name`, `capability_type`, `description`, `input_schema`, `available`, `version`. Statt die JSON-Spalte zu parsen, direkt aus `node_capabilities` lesen.

```python
# Statt _parse_capabilities(row["capabilities"]):
nc_rows = conn.execute(
    "SELECT capability_name, capability_type, capability_version, description, input_schema, available "
    "FROM node_capabilities WHERE node_id = ?",
    (row["node_id"],),
).fetchall()
for nc in nc_rows:
    cap = {
        "name": nc["capability_name"],
        "type": nc["capability_type"],
        "version": nc["capability_version"],
        "description": nc["description"],
        "input_schema": _parse(nc["input_schema"]),
        "available": bool(nc["available"]),
    }
    # ... weiter wie bisher
```

### 2. Fallback für Nodes ohne `node_capabilities`-Einträge
Falls ein Node in `node_capabilities` keine Einträge hat (z.B. weil er noch nie geheartbeatet hat), aus der JSON-Spalte lesen als Fallback.

### 3. Tests
- Test dass `get_capabilities()` keine Capabilities von Nodes anzeigt die nie geheartbeatet haben
- Test dass nach Heartbeat mit `replace_capabilities=True` alte Capabilities verschwinden

## Reihenfolge
1. `get_capabilities()` umbauen auf `node_capabilities`-Tabelle
2. Fallback für Nodes ohne `node_capabilities`
3. Tests
4. Doku (CHANGELOG)
