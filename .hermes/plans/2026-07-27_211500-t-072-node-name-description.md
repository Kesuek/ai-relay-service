# T-072: Node-Name + Description per Heartbeat

> **Goal:** Node kann `node_name` und `description` in der Capability-YAML setzen.
> Der Heartbeat überträgt sie an den Server, der die DB updated.
> `node list`/`node info` zeigen die Description an.

**Architecture:** Top-Level-Felder in `capabilities.yaml` → Daemon heartbeatet sie mit
→ Server updated `nodes`-Tabelle → CLI zeigt sie an.

**Tech Stack:** Python, FastAPI, Pydantic, SQLite

---

## Task 1: Server — Heartbeat-Modelle + DB-Update

**Objective:** `HeartbeatRequest`/`NodeHeartbeatRequest` um `node_name` + `description` erweitern.
`heartbeat()` updated die Felder in der DB.

**Files:**
- Modify: `src/relay_server/models/__init__.py:351-365`
- Modify: `src/relay_server/core/discovery.py:44-132`

**Step 1: Modelle erweitern**

In `models/__init__.py`:
```python
class HeartbeatRequest(BaseModel):
    load: Optional[float] = Field(None, ge=0.0, le=100.0)
    queue_depth: Optional[int] = Field(None, ge=0)
    available: Optional[bool] = None
    endpoint: Optional[str] = Field(None, max_length=2048)
    capabilities: Optional[List[CapabilityStatus]] = None
    node_name: Optional[str] = Field(None, max_length=128)
    description: Optional[str] = Field(None, max_length=1024)

class NodeHeartbeatRequest(BaseModel):
    load: Optional[float] = Field(None, ge=0.0, le=100.0)
    queue_depth: Optional[int] = Field(None, ge=0)
    available: Optional[bool] = None
    endpoint: Optional[str] = Field(None, max_length=2048)
    capabilities: Optional[List[dict[str, Any]]] = None
    node_name: Optional[str] = Field(None, max_length=128)
    description: Optional[str] = Field(None, max_length=1024)
```

**Step 2: Heartbeat-Funktion erweitern**

In `discovery.py`, nach dem `endpoint`-Block (ca. Zeile 86):
```python
        if endpoint is not None:
            updates.append("endpoint = ?")
            params.append(endpoint)
```
einfügen:
```python
        if node_name is not None:
            updates.append("node_name = ?")
            params.append(node_name)
        if description is not None:
            updates.append("description = ?")
            params.append(description)
```

Dazu die `heartbeat()`-Signatur um `node_name` und `description` erweitern:
```python
def heartbeat(
    node_id: str,
    load: Optional[float] = None,
    queue_depth: Optional[int] = None,
    available: Optional[bool] = None,
    endpoint: Optional[str] = None,
    capabilities: Optional[List[Dict[str, Any]]] = None,
    replace_capabilities: bool = False,
    node_name: Optional[str] = None,
    description: Optional[str] = None,
) -> bool:
```

**Step 3: `_node_row_to_dict()` um `description` erweitern**

In `discovery.py:490-502`:
```python
def _node_row_to_dict(row: Any) -> Dict[str, Any]:
    return {
        "node_id": row["node_id"],
        "node_name": row["node_name"],
        "description": row.get("description"),
        "capabilities": _parse_capabilities(row["capabilities"]),
        ...
    }
```

**Step 4: `list_nodes()` + `get_node()` SELECTs um `description` erweitern**

In `discovery.py:158-159` und `180-181`:
```python
"SELECT node_id, node_name, description, endpoint, capabilities, load, queue_depth, "
```

**Step 5: Test**

```bash
.venv/bin/python -m pytest tests/ -x -q
```
Erwartet: Alle Tests grün (keine Regression).

---

## Task 2: Node — Heartbeat sendet node_name + description

**Objective:** `RelayClient.heartbeat()` liest `node_name` + `description` aus der
Meta-Datei (`ai-relay-agent.json`) und sendet sie im Heartbeat mit.

**Files:**
- Modify: `nodes/common/node_cli.py:261-280`

**Step 1: `RelayClient.heartbeat()` erweitern**

In `node_cli.py`, in `def heartbeat(self, caps, in_flight)`:
```python
    def heartbeat(self, caps: list[dict[str, Any]], in_flight: dict[str, int]) -> dict[str, Any]:
        body: dict[str, Any] = {
            "load": self._compute_load(),
            "queue_depth": sum(in_flight.values()),
            "available": True,
            "capabilities": caps,
        }
        # T-072: node_name + description aus der Meta-Datei
        node_name = self.meta.get("node_name")
        if node_name:
            body["node_name"] = node_name
        description = self.meta.get("description")
        if description:
            body["description"] = description
        ...
```

**Step 2: Test**

```bash
.venv/bin/python -m nodes.common.node_cli heartbeat
```
Erwartet: Heartbeat 200 OK, Server hat node_name + description.

---

## Task 3: CLI — node list + node info zeigen Description

**Objective:** `node list` zeigt Description (gekürzt), `node info` zeigt sie vollständig.

**Files:**
- Modify: `nodes/common/node_cli.py` (in `_cmd_node_list` und `_cmd_node_info`)

**Step 1: `_cmd_node_list`**

Nach `Caps:`-Zeile einfügen:
```python
        desc = n.get("description", "")
        if desc:
            print(f"      Desc:     {desc[:60]}{'...' if len(desc) > 60 else ''}")
```

**Step 2: `_cmd_node_info`**

Nach `Registered:`-Zeile einfügen:
```python
    desc = node.get("description", "")
    if desc:
        print(f"Description: {desc}")
```

**Step 3: Test**

```bash
.venv/bin/python -m nodes.common.node_cli node list
.venv/bin/python -m nodes.common.node_cli node info 84K73W47
```

---

## Task 4: Doku

**Files:**
- Modify: `docs/node/capabilities.md` — `node_name` + `description` als Top-Level-Felder
- Modify: `docs/node/cli-reference.md` — `node info` zeigt Description
- Modify: `CHANGELOG.md`

---

## Abschliessende Antwort für das Project Board

- `TASKS.md`: T-072 auf `done`
- `DECISIONS.md`: Eintrag mit Datum
- `PLAN.md`: Phase 14-Checkbox für T-072

---

## OpenCode-Output

`.hermes/opencode-output/t-072-node-name-description/`
mit `STATUS.md`, `TASKS.md`, `DECISIONS.md`, `VERIFICATION.md`, `LOG.md`
