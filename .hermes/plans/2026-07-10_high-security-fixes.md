# HIGH Security & Reliability Fixes — Implementation Plan

> **Fuer OpenCode:** Tasks nacheinander abarbeiten. Nach jedem Task: `pytest` laufen lassen, alle Tests muessen gruen bleiben.

**Goal:** Drei HIGH-Findings aus dem GitHub-Code-Review beheben: Heartbeat Race Condition, fehlendes Audit Logging, EventBus Silent Drops.

**Betroffene Dateien:**
- `src/relay_server/core/discovery.py`
- `src/relay_server/core/db.py`
- `src/relay_server/core/events.py`
- `src/relay_server/api/v2/admin.py`
- `src/relay_server/api/v2/dashboard.py`
- `tests/test_discovery.py`
- `tests/test_events.py`

---

## Task 1: Heartbeat Race Condition — TOCTOU in mark_offline_nodes

**Was das bedeutet:** `mark_offline_nodes()` in `discovery.py` selektiert alle Nodes mit `last_seen < threshold` und updated sie dann in einem Batch. Wenn ein Node zwischen SELECT und UPDATE einen Heartbeat sendet, wird er trotzdem offline gesetzt — weil der Watchdog noch den alten `last_seen`-Wert gesehen hat. Der Node bekommt dann 403 bei Claims und muss sich neu registrieren.

**Objective:** Pro Node einzeln prüfen, ob `last_seen` immer noch unter dem Threshold liegt, bevor das UPDATE ausgeführt wird. Das SELECT liefert nur Kandidaten, das UPDATE prüft die Bedingung erneut in der WHERE-Klausel.

**Files:**
- Modify: `src/relay_server/core/discovery.py` (Zeilen 301-327)
- Test: `tests/test_discovery.py`

**Step 1: `mark_offline_nodes()` umbauen**

In `src/relay_server/core/discovery.py` die Funktion `mark_offline_nodes()` aendern:

```python
def mark_offline_nodes() -> List[str]:
    """Mark approved/online nodes as offline if heartbeat timeout exceeded.

    Admin nodes do not send heartbeats and are therefore excluded.
    Uses a re-check in the UPDATE WHERE clause to avoid TOCTOU races:
    a node that heartbeats between SELECT and UPDATE will not be marked offline.
    """
    threshold = _format_time(_node_timeout_threshold())
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT node_id FROM nodes
            WHERE status IN ('approved', 'online') AND last_seen < ? AND role != 'admin'
            """,
            (threshold,),
        ).fetchall()
        candidate_ids = [r["node_id"] for r in rows]
        if not candidate_ids:
            return []

        # Re-check last_seen in the UPDATE to avoid TOCTOU:
        # only mark offline if last_seen is STILL below threshold.
        conn.executemany(
            """
            UPDATE nodes SET status = 'offline', available = 0
            WHERE node_id = ? AND last_seen < ?
            """,
            [(nid, threshold) for nid in candidate_ids],
        )
        conn.commit()

        # Determine which nodes were actually updated (the UPDATE may have
        # matched 0 rows if a heartbeat came in between SELECT and UPDATE).
        offline_ids = [
            nid for nid in candidate_ids
            if conn.execute(
                "SELECT status FROM nodes WHERE node_id = ?", (nid,)
            ).fetchone()["status"] == "offline"
        ]

        for nid in offline_ids:
            event_bus.publish_sync("node_offline", {"node_id": nid})
        return offline_ids
    finally:
        conn.close()
```

**Aenderung im Detail:**
- Das UPDATE enthaelt jetzt `AND last_seen < ?` — wenn der Node zwischenzeitlich geheartbeatet hat, wird er nicht geupdated
- Nach dem UPDATE wird pro Node der Status gelesen, um die tatsaechlich offline gesetzten IDs zu ermitteln
- Events werden nur fuer tatsaechlich offline gesetzte Nodes gefeuert

**Step 2: Tests laufen**

```bash
cd /home/felix/projects/ai-relay-service
source .venv/bin/activate
.venv/bin/python -m pytest tests/test_discovery.py -x -q --tb=short 2>&1 | tail -10
```

Expected: ALL PASSED

**Step 3: Commit**

```bash
git add src/relay_server/core/discovery.py
git commit -m "fix(discovery): TOCTOU race in mark_offline_nodes — re-check last_seen in UPDATE WHERE clause"
```

---

## Task 2: Audit Logging — audit_logs-Tabelle + Logging in Admin-Endpoints

**Was das bedeutet:** Admin-Aktionen wie Node-Approval, Token-Ausstellung und Node-Loeschung hinterlassen keine Spur. Bei einem Security-Vorfall kann nicht nachvollzogen werden, wer was wann getan hat. Das ist ein Compliance-Problem.

**Objective:** Eine `audit_logs`-Tabelle in SQLite anlegen und in allen Admin-Endpunkten (approve, token, delete) Eintraege schreiben.

**Files:**
- Modify: `src/relay_server/core/db.py` (Schema + Migration)
- Modify: `src/relay_server/api/v2/admin.py` (Logging in approve, token, delete)
- Test: `tests/test_discovery.py` oder `tests/test_dashboard.py`

**Step 1: audit_logs-Tabelle in db.py**

In `src/relay_server/core/db.py` in `_schema()` nach den artifacts-Tabellen einfuegen:

```python
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            log_id TEXT PRIMARY KEY,
            actor_id TEXT NOT NULL,
            actor_name TEXT,
            action TEXT NOT NULL,
            resource_type TEXT,
            resource_id TEXT,
            details TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_logs_created ON audit_logs(created_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_logs_actor ON audit_logs(actor_id)"
    )
```

**Step 2: Migration fuer bestehende DBs**

In `_run_migrations()` in `db.py`:

```python
    # Ensure audit_logs table exists (migration for existing databases).
    table_names = [
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    ]
    if "audit_logs" not in table_names:
        conn.execute("""
            CREATE TABLE audit_logs (
                log_id TEXT PRIMARY KEY,
                actor_id TEXT NOT NULL,
                actor_name TEXT,
                action TEXT NOT NULL,
                resource_type TEXT,
                resource_id TEXT,
                details TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_logs_created ON audit_logs(created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_logs_actor ON audit_logs(actor_id)"
        )
```

**Step 3: Hilfsfunktion `log_audit_event()` in db.py**

```python
import secrets

def log_audit_event(
    actor_id: str,
    action: str,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    details: Optional[str] = None,
    actor_name: Optional[str] = None,
) -> None:
    """Write an audit log entry."""
    from datetime import datetime, timezone
    conn = get_conn()
    try:
        log_id = f"aud_{secrets.token_urlsafe(12)}"
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT INTO audit_logs (log_id, actor_id, actor_name, action,
                                    resource_type, resource_id, details, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (log_id, actor_id, actor_name, action,
             resource_type, resource_id, details, now),
        )
        conn.commit()
    finally:
        conn.close()
```

**Step 4: Logging in admin.py**

In `src/relay_server/api/v2/admin.py`:

Nach `from relay_server.core.auth import approve_node` import hinzufuegen:
```python
from relay_server.core.db import log_audit_event
```

In `admin_approve_node` (Zeile 46-65) vor dem return:
```python
    log_audit_event(
        actor_id=ctx.node_id,
        actor_name=ctx.node_name,
        action="node.approve",
        resource_type="node",
        resource_id=node_id,
        details=f"role={body.role}",
    )
    return _build_token_response(token)
```

In `admin_issue_node_token` (Zeile 68-107) vor dem return:
```python
    log_audit_event(
        actor_id=ctx.node_id,
        actor_name=ctx.node_name,
        action="node.issue_token",
        resource_type="node",
        resource_id=node_id,
    )
    return _build_token_response(token)
```

In `admin_delete_node` (Zeile 110-153) vor dem return:
```python
    log_audit_event(
        actor_id=ctx.node_id,
        actor_name=ctx.node_name,
        action="node.delete",
        resource_type="node",
        resource_id=node_id,
    )
    return {"deleted": True, "node_id": node_id}
```

**Step 5: Tests laufen**

```bash
cd /home/felix/projects/ai-relay-service
source .venv/bin/activate
.venv/bin/python -m pytest tests/test_discovery.py tests/test_dashboard.py -x -q --tb=short 2>&1 | tail -10
```

Expected: ALL PASSED

**Step 6: Commit**

```bash
git add src/relay_server/core/db.py src/relay_server/api/v2/admin.py
git commit -m "feat(audit): add audit_logs table and log admin actions (approve, token, delete)"
```

---

## Task 3: EventBus Silent Drops — dropped-Zaehler exponieren + Warn-Event

**Was das bedeutet:** Der `_Subscriber.dropped`-Zaehler in `events.py` wird inkrementiert, wenn ein Subscriber zu langsam ist und Events aus der Queue fallen. Aber niemand fragt diesen Zaehler ab — der Subscriber merkt nicht, dass ihm Events fehlen. Bei Cluster-Events wie `node_offline` oder `stage_claimed` kann das zu inkonsistenten Zustaenden fuehren.

**Objective:** Den `dropped`-Zaehler als Teil des SSE-Events exponieren (als `X-Dropped`-Header oder im Event-Meta) und ein Warn-Event feuern, wenn `dropped` einen Threshold ueberschreitet.

**Files:**
- Modify: `src/relay_server/core/events.py` (dropped im SSE-Format, Warn-Event bei Threshold)
- Test: `tests/test_events.py`

**Step 1: dropped-Zaehler in SSE-Event aufnehmen**

In `src/relay_server/core/events.py` die `_format_sse`-Funktion erweitern, sodass sie den dropped-Zaehler als `X-Dropped`-Header im SSE-Format mitschickt:

```python
def _format_sse(event: dict, dropped: int = 0) -> str:
    """Format an event as SSE with optional dropped count."""
    lines = [f"event: {event['type']}", f"data: {json.dumps(event)}"]
    if dropped > 0:
        lines.insert(1, f"X-Dropped: {dropped}")
    return "\n".join(lines) + "\n\n"
```

**Step 2: dropped-Zaehler in subscribe()-Methode uebergeben**

In der `subscribe()`-Methode (Zeile 62-84) beim Yielding das `dropped` aus dem Subscriber uebergeben:

```python
    async def subscribe(
        self,
        node_id: Optional[str] = None,
        event_types: Optional[Iterable[str]] = None,
    ) -> AsyncGenerator[str, None]:
        sid = self._generate_id()
        types_set: Optional[Set[str]] = set(event_types) if event_types else None
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._queue_size)
        loop = asyncio.get_running_loop()
        self._subscribers[sid] = _Subscriber(sid, node_id, queue, loop, types_set)
        try:
            while True:
                event = await queue.get()
                sub = self._subscribers.get(sid)
                dropped = sub.dropped if sub else 0
                yield _format_sse(event, dropped=dropped)
        except asyncio.CancelledError:
            pass
        finally:
            self._subscribers.pop(sid, None)
```

**Step 3: Warn-Event bei Threshold-Ueberschreitung**

In `_Subscriber.put_nowait()` ein Warn-Event feuern, wenn `dropped` einen Threshold ueberschreitet (z.B. 100). Dafuer braucht der Subscriber eine Referenz auf den EventBus:

```python
@dataclass
class _Subscriber:
    subscriber_id: str
    node_id: Optional[str]
    queue: asyncio.Queue
    loop: asyncio.AbstractEventLoop
    event_types: Optional[Set[str]] = None
    dropped: int = field(default=0, init=False)
    _event_bus: Optional[EventBus] = field(default=None, init=False)

    def put_nowait(self, event: dict) -> None:
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            self.dropped += 1
            # Warn when drops exceed threshold
            if self.dropped == 100 and self._event_bus is not None:
                self._event_bus._publish_internal(
                    "subscriber_lagging",
                    {
                        "subscriber_id": self.subscriber_id,
                        "node_id": self.node_id,
                        "dropped": self.dropped,
                    },
                )
```

Dafuer muss in `subscribe()` der `_event_bus` gesetzt werden:

```python
        self._subscribers[sid] = _Subscriber(sid, node_id, queue, loop, types_set)
        self._subscribers[sid]._event_bus = self
```

Und eine `_publish_internal()`-Methode, die ohne History-Schreiben auskommt (um Endlos-Rekursion zu vermeiden):

```python
    def _publish_internal(self, event_type: str, payload: dict) -> None:
        """Publish an internal event without writing to history (avoids recursion)."""
        event = _make_event(event_type, payload)
        for sub in list(self._subscribers.values()):
            if sub.event_types is not None and event_type not in sub.event_types:
                continue
            try:
                sub.loop.call_soon_threadsafe(sub.put_nowait, event)
            except RuntimeError:
                pass
```

**Wichtig:** `_publish_internal` darf nicht `self._history.append()` aufrufen, sonst erzeugt das subscriber_lagging-Event selbst wieder History-Eintraege — das ist OK, aber es darf nicht zu einer Endlosschleife fuehren (der Threshold-Check feuert nur einmal bei `dropped == 100`).

**Step 4: Tests laufen**

```bash
cd /home/felix/projects/ai-relay-service
source .venv/bin/activate
.venv/bin/python -m pytest tests/test_events.py -x -q --tb=short 2>&1 | tail -10
```

Expected: ALL PASSED

**Step 5: Commit**

```bash
git add src/relay_server/core/events.py
git commit -m "fix(events): expose dropped counter in SSE stream, add subscriber_lagging warning event"
```

---

## Abschliessende Antwort fuer das Project Board

Nach erfolgreicher Implementierung:

1. **TASKS.md aktualisieren:**
   - T-013 (Heartbeat Race Condition) → `done`
   - T-014 (Audit Logging) → `done`
   - T-015 (EventBus Silent Drops) → `done`

2. **DECISIONS.md erweitern:**
   - 2026-07-10: HIGH-Fixes aus GitHub-Review implementiert
   - `mark_offline_nodes()`: TOCTOU-Schutz via `AND last_seen < ?` in UPDATE-WHERE-Klausel
   - `audit_logs`-Tabelle: loggt approve, issue_token, delete mit actor_id, action, resource, timestamp
   - EventBus: `X-Dropped`-Header im SSE-Stream, `subscriber_lagging`-Warn-Event bei 100 Drops

3. **PLAN.md:**
   - Phase 6: T-013, T-014, T-015 als erledigt markieren

## OpenCode-Output

Nach Abarbeitung legt OpenCode sein Ergebnis ab unter:
`.hermes/opencode-output/2026-07-10_high-security-fixes/`
mit `STATUS.md`, `TASKS.md`, `DECISIONS.md`, `VERIFICATION.md`, `LOG.md`.
