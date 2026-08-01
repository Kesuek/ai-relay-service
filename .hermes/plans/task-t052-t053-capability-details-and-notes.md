# Plan: T-052 Task-Notes + T-053 Capability-Details

## Übersicht
Zwei unabhängige Features in einem Plan:
- **T-052:** Nodes können während der Bearbeitung Text-Notizen an einem Task hinterlassen (Mini-Chat)
- **T-053:** Server liefert beim Claim und Task-View die Capability-Details (description, type, input_schema) mit

---

## T-052: Task-Notes

### 1. DB-Migration: Tabelle `task_notes`
**Datei:** `src/relay_server/core/db.py`

Neue Tabelle in `_init_schema()`:
```sql
CREATE TABLE IF NOT EXISTS task_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    node_id TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_task_notes_task_id ON task_notes(task_id);
```

### 2. Neuer API-Endpoint: `POST /relay/v2/scheduler/tasks/{task_id}/notes`
**Datei:** `src/relay_server/api/v2/scheduler.py`

Neuer Endpoint:
```python
@router.post("/tasks/{task_id}/notes")
async def scheduler_add_note(
    task_id: str,
    body: NoteRequest,
    ctx: AuthContext = Depends(get_approved_context),
):
    # Prüfen ob Task existiert
    conn = get_conn()
    try:
        row = conn.execute("SELECT task_id FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
        now = _format_time(datetime.utcnow())
        conn.execute(
            "INSERT INTO task_notes (task_id, node_id, message, created_at) VALUES (?, ?, ?, ?)",
            (task_id, ctx.node_id, body.message, now),
        )
        conn.commit()
        return {"status": "created", "task_id": task_id, "node_id": ctx.node_id, "message": body.message, "created_at": now}
    finally:
        conn.close()
```

Dazu neues Pydantic-Modell `NoteRequest` in `src/relay_server/models/task.py` und `src/relay_server/models/__init__.py`:
```python
class NoteRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
```

### 3. `GET /tasks/{id}` inkludiert `notes`-Array
**Datei:** `src/relay_server/core/scheduler.py` — in `get_task()`

Nach dem Laden der artifacts, Notes laden:
```python
note_rows = conn.execute(
    "SELECT id, node_id, message, created_at FROM task_notes WHERE task_id = ? ORDER BY created_at ASC",
    (task_id,),
).fetchall()
task["notes"] = [
    {"id": r["id"], "node_id": r["node_id"], "message": r["message"], "created_at": r["created_at"]}
    for r in note_rows
]
```

`TaskView`-Modell in `models/task.py` und `models/__init__.py` um `notes`-Feld erweitern:
```python
class TaskView(BaseModel):
    task: TaskSummary
    stages: List[StageSummary]
    artifacts: List[ArtifactReference]
    notes: List[NoteResponse] = Field(default_factory=list)
```

Dazu `NoteResponse`-Modell:
```python
class NoteResponse(BaseModel):
    id: int
    node_id: str
    message: str
    created_at: str
```

### 4. `_task_to_view()` in `api/v2/scheduler.py` anpassen
Notes aus dem task-dict mitgeben:
```python
def _task_to_view(task: Dict[str, Any]) -> TaskView:
    return TaskView(
        task=TaskSummary(**task),
        stages=[StageSummary(**s) for s in task["stages"]],
        artifacts=task.get("artifacts", []),
        notes=[NoteResponse(**n) for n in task.get("notes", [])],
    )
```

### 5. Neuer CLI-Befehl: `node-cli task note <id> <message>`
**Datei:** `nodes/common/node_cli.py`

Neue Subcommand-Parser (im `task`-Parser):
```python
p_note = p_task_sub.add_parser("note", help="Add a note to a task.")
p_note.add_argument("task_id", help="Task ID to add a note to.")
p_note.add_argument("message", help="Note text.")
p_note.set_defaults(func=_cmd_task_note)
```

Neue Handler-Funktion:
```python
def _cmd_task_note(args):
    client = _build_client()
    r = client._post_with_retry(f"/relay/v2/scheduler/tasks/{args.task_id}/notes", {"message": args.message})
    if r.status_code == 200:
        data = r.json()
        print(f"✅ Note added to task {args.task_id}")
        print(f"   {data['message']} ({data['created_at']})")
    elif r.status_code == 404:
        print(f"❌ Task {args.task_id} not found")
    else:
        print(f"❌ Error: {r.status_code} {r.text}")
```

### 6. `node-cli task wait` zeigt neue Notes live an
**Datei:** `nodes/common/node_cli.py` — in `_cmd_task_wait()`

Nach jedem Poll die Notes checken und neue anzeigen. Dazu `_last_note_count` tracken:
```python
def _cmd_task_wait(args):
    client = _build_client()
    last_note_count = 0
    while True:
        r = client._get_with_retry(f"/relay/v2/scheduler/tasks/{args.task_id}")
        if r.status_code != 200:
            print(f"⚠️  Error polling task: {r.status_code}")
            time.sleep(args.interval)
            continue
        data = r.json()
        task = data.get("task", {})
        stages = data.get("stages", [])
        notes = data.get("notes", [])
        
        # Neue Notes anzeigen
        if len(notes) > last_note_count:
            for n in notes[last_note_count:]:
                print(f"💬 [{n['node_id']}] {n['message']} ({n['created_at']})")
            last_note_count = len(notes)
        
        # Status prüfen
        if task.get("status") in ("completed", "failed", "cancelled"):
            # Task-Result anzeigen (bestehender Code)
            ...
            break
        
        print(f"\r⏳ {task.get('status', 'unknown')} — {sum(1 for s in stages if s['status'] == 'completed')}/{len(stages)} stages completed...", end="")
        time.sleep(args.interval)
```

### 7. Doku aktualisieren
**Datei:** `docs/reference/api.md` — Neuen Endpoint eintragen:
```markdown
| POST | /relay/v2/scheduler/tasks/{task_id}/notes | Note hinzufügen | `{"message": "..."}` | 200, 404 |
```

**Datei:** `docs/node/cli-reference.md` — Neuen Subcommand eintragen:
```markdown
### task note
`node-cli task note <task_id> <message>`
Fügt eine Text-Notiz an einem Task hinzu. Alle Nodes die den Task abfragen sehen die Notiz.
```

**Datei:** `CHANGELOG.md` — Eintrag hinzufügen.

---

## T-053: Capability-Details im Claim-Response und Task-View

### 1. Heartbeat sendet Capability-Details mit
**Datei:** `nodes/common/node_cli.py` — in der Heartbeat-Logik

Der Heartbeat sendet bereits Capabilities. Aktuell wird nur `name` und `available` gesendet. Erweitern um `description`, `type`, `input_schema`:

In `_build_heartbeat_body()` oder der entsprechenden Stelle, wo die Capability-Liste für den Heartbeat gebaut wird, die Felder aus dem YAML-Profil mitnehmen. Die Capability-Objekte haben bereits `description`, `type`, `input_schema` — sie müssen nur in den Heartbeat-Body übernommen werden.

### 2. Server resolved Capability-Details in `claim_stage()`
**Datei:** `src/relay_server/core/scheduler.py` — in `claim_stage()`

Nach erfolgreichem Claim (vor `return _stage_row_to_dict(...)`) die Capability-Details aus der node_capabilities-Tabelle laden und ans stage-dict anhängen:

```python
# Capability-Details laden
cap_details = conn.execute(
    "SELECT capability_name, capability_type, description, input_schema FROM node_capabilities WHERE node_id = ? AND capability_name = ?",
    (node_id, row["capability"]),
).fetchone()
stage_dict = _stage_row_to_dict(...)
if cap_details:
    stage_dict["capability_details"] = {
        "name": cap_details["capability_name"],
        "type": cap_details["capability_type"],
        "description": cap_details["description"],
        "input_schema": _parse(cap_details["input_schema"]),
    }
return stage_dict
```

### 3. `GET /tasks/{id}` liefert capability_details pro Stage
**Datei:** `src/relay_server/core/scheduler.py` — in `get_task()`

In der Stage-Schleife nach dem Laden der stages für jede Stage die Capability-Details auflösen:

```python
task["stages"] = []
for r in stage_rows:
    stage = _stage_row_to_dict(r)
    # Capability-Details für diese Stage auflösen
    cap_row = conn.execute(
        "SELECT capability_name, capability_type, description, input_schema FROM node_capabilities WHERE capability_name = ? LIMIT 1",
        (r["capability"],),
    ).fetchone()
    if cap_row:
        stage["capability_details"] = {
            "name": cap_row["capability_name"],
            "type": cap_row["capability_type"],
            "description": cap_row["capability_description"],
            "input_schema": _parse(cap_row["input_schema"]),
        }
    task["stages"].append(stage)
```

### 4. StageSummary-Modell um capability_details erweitern
**Datei:** `src/relay_server/models/task.py` und `src/relay_server/models/__init__.py`

```python
class StageSummary(BaseModel):
    # ... bestehende Felder ...
    capability_details: Optional[Dict[str, Any]] = Field(None, description="Resolved capability metadata (name, type, description, input_schema)")
```

### 5. `node-cli claim` zeigt Capability-Details an
**Datei:** `nodes/common/node_cli.py` — in `_cmd_claim()`

Nach erfolgreichem Claim die `capability_details` aus dem Stage-Response auslesen und anzeigen:
```python
if stage.get("capability_details"):
    cd = stage["capability_details"]
    print(f"  Capability: {cd.get('name', '?')}")
    if cd.get("description"):
        print(f"  Description: {cd['description']}")
    if cd.get("type"):
        print(f"  Type: {cd['type']}")
    if cd.get("input_schema"):
        print(f"  Input Schema: {json.dumps(cd['input_schema'], indent=2)}")
```

### 6. `node-cli task result/wait` zeigt Capability-Details pro Stage
**Datei:** `nodes/common/node_cli.py` — in `_cmd_task_result()` und `_cmd_task_wait()`

In der Stage-Anzeige die `capability_details` mit ausgeben:
```python
for s in stages:
    print(f"  {'✅' if s['status'] == 'completed' else '⏳'} {s['stage_name']} [{s['capability']}] — {s['status']}")
    if s.get("capability_details"):
        cd = s["capability_details"]
        if cd.get("description"):
            print(f"     Description: {cd['description']}")
```

### 7. Doku aktualisieren
**Datei:** `docs/node/capabilities.md` — YAML-Format um `description`, `type`, `input_schema` ergänzen.

**Datei:** `docs/node/cli-reference.md` — `claim`-Subcommand um capability_details-Output ergänzen.

**Datei:** `CHANGELOG.md` — Eintrag hinzufügen.

---

## Tests

### T-052 Tests
- `tests/test_scheduler.py`: Test für `POST /tasks/{id}/notes` (200, 404)
- `tests/test_scheduler.py`: Test dass `GET /tasks/{id}` notes-Array enthält
- `tests/nodes/test_node_cli.py`: Test für `node-cli task note`

### T-053 Tests
- `tests/test_scheduler.py`: Test dass `POST /claim` capability_details im Response hat
- `tests/test_scheduler.py`: Test dass `GET /tasks/{id}` capability_details pro Stage hat
- Bestehende Tests die exakte Dict-Matches auf StageSummary machen anpassen (neues optionales Feld)

---

## Reihenfolge
1. DB-Migration (Tabelle task_notes)
2. Modelle (NoteRequest, NoteResponse, capability_details in StageSummary)
3. Server-Endpoints (POST notes, GET tasks inkl. notes + capability_details)
4. Scheduler-Logik (claim_stage capability_details, get_task notes + capability_details)
5. CLI (task note, claim/task result/wait Anzeige)
6. Doku (api.md, cli-reference.md, capabilities.md, CHANGELOG.md)
7. Tests
