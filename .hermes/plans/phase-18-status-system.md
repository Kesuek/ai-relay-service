# Plan: Phase 18 — Zentrales Status-System

## Scope
Einheitliches Status-System für Nodes, Tasks, Stages und User. Zentrale Registry in `core/status.py` mit Kategorien (AVAILABLE, BUSY, PENDING, TERMINAL, OFFLINE). Node-Busy (manuell + auto), SSE-Events, Dashboard-Rendering, CLI-Befehle, User-Status vorbereitet, Dokumentation.

## Tasks

### T-078: `core/status.py` — Zentrale Status-Registry

**Neue Datei:** `src/relay_server/core/status.py`

```python
"""Central status registry for all entity types.

Each status has a name and a category. The scheduler and dashboard
query by category instead of hardcoded string lists, making it easy
to add new status values without touching business logic.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Dict, List


class StatusCategory(enum.Enum):
    AVAILABLE = "available"   # online, idle, approved, active
    BUSY = "busy"             # busy, running, claimed, maintenance
    PENDING = "pending"       # pending, awaiting_subtasks, needs_input, accepted
    TERMINAL = "terminal"     # completed, failed, timed_out, cancelled
    OFFLINE = "offline"       # offline, inactive


@dataclass
class StatusDef:
    name: str
    category: StatusCategory
    allowed_transitions: List[str] = field(default_factory=list)


# ── Node statuses ────────────────────────────────────────────────

NODE_STATUSES: Dict[str, StatusDef] = {
    "offline":     StatusDef("offline",     StatusCategory.OFFLINE,   ["pending"]),
    "pending":     StatusDef("pending",     StatusCategory.PENDING,   ["approved", "offline"]),
    "approved":    StatusDef("approved",    StatusCategory.AVAILABLE, ["online", "offline"]),
    "online":      StatusDef("online",      StatusCategory.AVAILABLE, ["busy", "idle", "offline", "maintenance"]),
    "idle":        StatusDef("idle",        StatusCategory.AVAILABLE, ["busy", "online", "offline"]),
    "busy":        StatusDef("busy",         StatusCategory.BUSY,     ["idle", "online", "offline"]),
    "maintenance": StatusDef("maintenance",  StatusCategory.BUSY,     ["offline"]),
}

# ── Task statuses ────────────────────────────────────────────────

TASK_STATUSES: Dict[str, StatusDef] = {
    "pending":           StatusDef("pending",           StatusCategory.PENDING,   ["accepted", "running", "cancelled"]),
    "accepted":          StatusDef("accepted",          StatusCategory.PENDING,   ["running", "awaiting_subtasks", "cancelled"]),
    "running":           StatusDef("running",            StatusCategory.BUSY,     ["completed", "failed", "timed_out", "cancelled"]),
    "awaiting_subtasks": StatusDef("awaiting_subtasks",  StatusCategory.PENDING,   ["running", "cancelled"]),
    "needs_input":       StatusDef("needs_input",        StatusCategory.PENDING,   ["running", "cancelled"]),
    "completed":         StatusDef("completed",          StatusCategory.TERMINAL,  []),
    "failed":            StatusDef("failed",             StatusCategory.TERMINAL,  []),
    "timed_out":         StatusDef("timed_out",          StatusCategory.TERMINAL,  []),
    "cancelled":         StatusDef("cancelled",          StatusCategory.TERMINAL,  []),
}

# ── Stage statuses ──────────────────────────────────────────────

STAGE_STATUSES: Dict[str, StatusDef] = {
    "pending":   StatusDef("pending",   StatusCategory.PENDING,   ["claimed", "accepted", "cancelled"]),
    "claimed":   StatusDef("claimed",    StatusCategory.BUSY,     ["completed", "failed", "timed_out", "pending"]),
    "accepted":  StatusDef("accepted",  StatusCategory.PENDING,   ["completed", "failed", "timed_out"]),
    "completed": StatusDef("completed", StatusCategory.TERMINAL,  []),
    "failed":    StatusDef("failed",    StatusCategory.TERMINAL,  []),
    "timed_out": StatusDef("timed_out", StatusCategory.TERMINAL,  []),
    "cancelled": StatusDef("cancelled", StatusCategory.TERMINAL,  []),
}

# ── User statuses ───────────────────────────────────────────────

USER_STATUSES: Dict[str, StatusDef] = {
    "active":   StatusDef("active",   StatusCategory.AVAILABLE, ["inactive"]),
    "inactive": StatusDef("inactive", StatusCategory.OFFLINE,   ["active"]),
}

# ── Combined lookup ──────────────────────────────────────────────

_ALL: Dict[str, StatusDef] = {}
for d in (NODE_STATUSES, TASK_STATUSES, STAGE_STATUSES, USER_STATUSES):
    _ALL.update(d)


def get_status(name: str) -> StatusDef | None:
    return _ALL.get(name)


def get_category(name: str) -> StatusCategory | None:
    sd = _ALL.get(name)
    return sd.category if sd else None


def is_terminal(name: str) -> bool:
    sd = _ALL.get(name)
    return sd is not None and sd.category == StatusCategory.TERMINAL


def is_busy(name: str) -> bool:
    sd = _ALL.get(name)
    return sd is not None and sd.category == StatusCategory.BUSY


def is_available(name: str) -> bool:
    sd = _ALL.get(name)
    return sd is not None and sd.category == StatusCategory.AVAILABLE


def is_pending(name: str) -> bool:
    sd = _ALL.get(name)
    return sd is not None and sd.category == StatusCategory.PENDING


def is_offline(name: str) -> bool:
    sd = _ALL.get(name)
    return sd is not None and sd.category == StatusCategory.OFFLINE


def can_transition(from_status: str, to_status: str) -> bool:
    sd = _ALL.get(from_status)
    if sd is None:
        return False
    return to_status in sd.allowed_transitions


def node_can_claim(node_status: str) -> bool:
    """A node can claim stages only when its status is AVAILABLE."""
    cat = get_category(node_status)
    return cat == StatusCategory.AVAILABLE


def node_is_claimable(node_status: str) -> bool:
    """A node is a valid claim target (not busy, not offline)."""
    cat = get_category(node_status)
    return cat in (StatusCategory.AVAILABLE, StatusCategory.PENDING)


# ── Dashboard colour mapping ───────────────────────────────────

STATUS_COLORS: Dict[StatusCategory, str] = {
    StatusCategory.AVAILABLE: "ok",     # green
    StatusCategory.BUSY:     "warn",    # yellow
    StatusCategory.PENDING:  "info",    # blue
    StatusCategory.TERMINAL: "muted",   # grey (individual statuses override: completed=ok, failed=bad)
    StatusCategory.OFFLINE:  "bad",     # red
}
```

**Änderungen:**
- NEU: `src/relay_server/core/status.py` — gesamte Registry
- Keine Änderungen an anderen Dateien (nur Import + Nutzung in folgenden Tasks)

---

### T-079: DB-Migration — `status`-Feld in Nodes-Tabelle

**Datei:** `src/relay_server/core/db.py`

1. **Neue Spalte `status` in `nodes`-Tabelle** — existiert bereits als `status TEXT DEFAULT 'pending'`. Keine Schema-Änderung nötig.
2. **Neue Spalte `status` in `users`-Tabelle** — `is_active BOOLEAN` bleibt, aber `status TEXT DEFAULT 'active'` hinzufügen.
3. **Additive Migration** in `_schema()`:
   ```python
   conn.execute("ALTER TABLE users ADD COLUMN status TEXT DEFAULT 'active'")
   ```
   (mit `IF NOT EXISTS`-ähnlichem Try/Except für Idempotenz)

**Änderungen:**
- `src/relay_server/core/db.py` — `_schema()`: `users`-Tabelle um `status`-Spalte ergänzen
- Keine Änderung an `nodes`-Tabelle (Spalte existiert bereits)

---

### T-080: Scheduler-Umbau auf Kategorie-Logik

**Datei:** `src/relay_server/core/scheduler.py`

1. **`claim_stage()`** — Node-Status-Prüfung auf Kategorie umstellen:
   ```python
   # Before:
   "SELECT capabilities FROM nodes WHERE node_id = ? AND status IN ('approved', 'online')"
   # After:
   from relay_server.core.status import node_can_claim
   # Prüfung: node_can_claim(node_status) statt status IN ('approved', 'online')
   ```
   Zusätzlich: BUSY-Nodes vom Claim ausschließen:
   ```python
   # Nach dem SELECT: wenn node_status == 'busy' → return None
   ```

2. **`release_or_fail_claims()`** — Terminal-Status-Prüfung auf Kategorie:
   ```python
   # Before:
   "WHERE status = 'claimed' AND claim_expires_at < ?"
   # After: unverändert (claimed ist weiterhin der einzige BUSY-Stage-Status)
   # Aber: _fail_tasks_if_all_stages_done() nutzt is_terminal() statt String-Tupel
   ```

3. **`enforce_timeouts()`** — Gleiches Pattern:
   ```python
   # Before:
   "WHERE status = 'claimed'"
   # After: unverändert
   # Aber: Terminal-Prüfung via is_terminal()
   ```

4. **`fail_orphaned_stages()`** — Node-Status-Prüfung auf Kategorie:
   ```python
   # Before:
   "WHERE status IN ('approved', 'online')"
   # After: node_is_claimable() oder Kategorie-Prüfung
   ```

5. **`_fail_tasks_if_all_stages_done()`** — Hilfsfunktion:
   ```python
   # Before: terminal_stage_status=("completed", "failed", "timed_out")
   # After: is_terminal() statt hartcodiertem Tupel
   ```

**Änderungen:**
- `src/relay_server/core/scheduler.py` — 5 Stellen umstellen
- `src/relay_server/core/discovery.py` — `mark_offline_nodes()`: Node-Status-Prüfung auf Kategorie

---

### T-081: Heartbeat + Auto-Busy

**Datei:** `src/relay_server/core/discovery.py` + `src/relay_server/models/__init__.py`

1. **Heartbeat-Modell** (`models/__init__.py`):
   ```python
   class HeartbeatRequest(BaseModel):
       # ... existing fields ...
       status: Optional[str] = Field(None, max_length=64)  # NEU: busy/idle/online
   ```

2. **Heartbeat-Endpoint** (`api/v2/discovery.py`):
   - Wenn `status` im Heartbeat gesetzt ist → `UPDATE nodes SET status = ?`
   - Validierung via `status.can_transition(old_status, new_status)`
   - Bei Status-Änderung: `event_bus.publish_sync("status_changed", ...)`

3. **Auto-Busy in `mark_offline_nodes()`** (`core/discovery.py`):
   - Load-Tracking: Wenn `load` über `load_cap` für N aufeinanderfolgende Heartbeats → Node auf `busy` setzen
   - Dafür: `nodes`-Tabelle um `consecutive_high_load INTEGER DEFAULT 0` ergänzen
   - Bei Heartbeat: wenn `load >= load_cap` → `consecutive_high_load += 1`, sonst reset auf 0
   - Bei `consecutive_high_load >= 3` → `status = 'busy'`
   - Sobald Load wieder fällt → `status = 'idle'` (oder `'online'`)

4. **Node-seitig** (`nodes/common/node_cli.py`):
   - Heartbeat-Body um `status`-Feld ergänzen
   - `node-cli node busy` → setzt `status: busy` im nächsten Heartbeat
   - `node-cli node idle` → setzt `status: idle`

**Änderungen:**
- `src/relay_server/models/__init__.py` — `HeartbeatRequest.status`-Feld
- `src/relay_server/api/v2/discovery.py` — Heartbeat-Endpoint: Status-Handling
- `src/relay_server/core/discovery.py` — `mark_offline_nodes()`: Auto-Busy-Logik
- `src/relay_server/core/db.py` — `_schema()`: `consecutive_high_load`-Spalte
- `nodes/common/node_cli.py` — Heartbeat-Body um `status`

---

### T-082: SSE-Events — `status_changed`

**Datei:** `src/relay_server/core/events.py` (keine Änderung — EventBus ist generisch)

**Neue Event-Typen** (Dokumentation in `concepts.md`):
- `status_changed` — payload: `{"entity_type": "node"|"task"|"stage"|"user", "entity_id": "...", "old_status": "...", "new_status": "..."}`

**Feuern bei:**
- `mark_offline_nodes()` → Node offline → `status_changed`
- Heartbeat mit Status-Änderung → `status_changed`
- `claim_stage()` → Stage claimed → `status_changed`
- `complete_stage()` → Stage completed → `status_changed`
- `release_or_fail_claims()` → Stage failed/released → `status_changed`
- `enforce_timeouts()` → Stage/ Task timed_out → `status_changed`
- `fail_orphaned_stages()` → Stage failed → `status_changed`
- Task-Status-Änderungen (create, complete, fail) → `status_changed`

**Änderungen:**
- `src/relay_server/core/scheduler.py` — `publish_sync("status_changed", ...)` an allen Status-Übergängen
- `src/relay_server/core/discovery.py` — `mark_offline_nodes()`: `status_changed`-Event
- `src/relay_server/api/v2/discovery.py` — Heartbeat: `status_changed`-Event

---

### T-083: Dashboard-Rendering — Farben pro Kategorie

**Datei:** `src/relay_server/static/dashboard.js`

1. **Status-Farb-Mapping** im JS:
   ```javascript
   const STATUS_COLORS = {
     available: 'ok',    // green
     busy: 'warn',       // yellow
     pending: 'info',    // blue
     terminal: 'muted',  // grey
     offline: 'bad',     // red
   };
   
   function statusColor(status) {
     // Server liefert status_category mit im Overview-Response
     const cat = STATUS_CATEGORIES[status] || 'offline';
     return STATUS_COLORS[cat] || 'muted';
   }
   ```

2. **Server-seitig** (`api/v2/dashboard.py` — `/api/overview`):
   - Jeder Node bekommt `status_category` im Response
   - Jeder Task bekommt `status_category`

3. **Node-Tabelle** — Status-Zelle nutzt `statusColor()`:
   ```javascript
   <span class="tag ${statusColor(n.status)}">${n.status}</span>
   ```

4. **Task-Tabelle** — Gleiches Pattern

**Änderungen:**
- `src/relay_server/static/dashboard.js` — `statusColor()`-Funktion + Status-Zellen
- `src/relay_server/api/v2/dashboard.py` — `status_category` im Overview-Response

---

### T-084: CLI-Befehle — `node-cli node busy/idle`

**Datei:** `nodes/common/node_cli.py`

1. **Neue Subcommands:**
   ```
   node-cli node busy    → setzt node.status = 'busy' im nächsten Heartbeat
   node-cli node idle    → setzt node.status = 'idle'
   node-cli node status  → zeigt aktuellen Node-Status (lokal + vom Server)
   ```

2. **Implementierung:**
   - `do_node_busy()` → schreibt `status: busy` in Meta-Datei, Heartbeat überträgt
   - `do_node_idle()` → schreibt `status: idle`
   - `do_node_status()` → zeigt lokalen Status + fragt Server nach aktuellem Status
   - `--json`-Support für alle drei

3. **Heartbeat-Anpassung:**
   - `heartbeat()` liest `self.meta.get("status")` und sendet es mit

**Änderungen:**
- `nodes/common/node_cli.py` — 3 neue Subcommands + Heartbeat-Status-Feld

---

### T-085: User-Status vorbereitet

**Datei:** `src/relay_server/core/db.py` + `src/relay_server/core/status.py`

1. **DB:** `users`-Tabelle um `status TEXT DEFAULT 'active'` ergänzen (T-079)
2. **Registry:** `USER_STATUSES` in `core/status.py` (T-078) — bereits definiert
3. **Keine aktive Logik** — Status wird gesetzt aber nicht ausgewertet. Später erweiterbar für:
   - Session-Timeout bei `inactive`
   - Dashboard-Filter "nur aktive User"
   - Task-Routing basierend auf User-Status

**Änderungen:**
- In T-078 und T-079 enthalten — kein separater Code nötig

---

### T-086: Dokumentation

1. **`docs/concepts.md`** — Neuer Abschnitt "Status System":
   - Status-Kategorien (AVAILABLE, BUSY, PENDING, TERMINAL, OFFLINE)
   - Node-Status-Transitionen (mit Diagramm)
   - Task/Stage-Status-Transitionen
   - Busy-Modus (manuell + auto)
   - `status_changed`-SSE-Event

2. **`docs/node/cli-reference.md`** — Neue Subcommands:
   - `node-cli node busy` — Node auf busy setzen
   - `node-cli node idle` — Node auf idle setzen
   - `node-cli node status` — Aktuellen Status anzeigen

3. **`docs/reference/api.md`** — Heartbeat-Request um `status`-Feld ergänzen

4. **`CHANGELOG.md`** — Phase 18 Eintrag

5. **`STATUS.md`** — Phase 18 als completed markieren

---

## Test-Änderungen

1. **`tests/test_status.py`** — NEU:
   - `test_status_registry_has_all_entries()` — Alle erwarteten Stati existieren
   - `test_status_categories()` — Jeder Status hat korrekte Kategorie
   - `test_transition_valid()` — Erlaubte Transitionen funktionieren
   - `test_transition_invalid()` — Nicht erlaubte Transitionen werden abgelehnt
   - `test_node_can_claim()` — Nur AVAILABLE-Nodes können claimen
   - `test_is_terminal()` — Terminal-Stati korrekt erkannt

2. **`tests/test_scheduler.py`** — Bestehende Tests:
   - Status-Prüfungen auf Kategorie-Logik umstellen (keine neuen Tests, bestehende müssen weiter grün sein)

3. **`tests/test_discovery.py`** — Bestehende Tests:
   - `mark_offline_nodes()`-Tests weiterhin grün

4. **`tests/test_node_cli.py`** — NEU (oder in bestehendem test_node_cli.py):
   - `test_node_busy_idle_commands()` — CLI-Befehle setzen Status korrekt

---

## Reihenfolge der Umsetzung

1. T-078: `core/status.py` — Basis für alles andere
2. T-079: DB-Migration — `status`-Feld + `consecutive_high_load`
3. T-080: Scheduler-Umbau — auf Kategorie-Logik
4. T-081: Heartbeat + Auto-Busy — Node-seitig + Server-seitig
5. T-082: SSE-Events — `status_changed` an allen Übergängen
6. T-083: Dashboard-Rendering — Farben pro Kategorie
7. T-084: CLI-Befehle — `node-cli node busy/idle/status`
8. T-085: User-Status — in T-078/079 enthalten
9. T-086: Dokumentation — concepts, cli-reference, api, CHANGELOG, STATUS

---

## Project Board Update (nach Abschluss)

- T-078 bis T-086: alle auf `✅ done`
- PLAN.md: Phase 18 Checkboxen auf `[x]`
- IDEAS.md: Status-System-Idee als umgesetzt markieren
- DECISIONS.md: Eintrag mit Datum, Begründung, betroffenen Tasks
