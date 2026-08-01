# T-075: Dynamic Node Routes — Implementation Plan

> **For Hermes:** Implement step by step. Each step = one `opencode run` cycle.

**Goal:** Nodes can declare API routes in their capability YAML (`routes:` block). The relay registers them dynamically as FastAPI routes when the node heartbeats, and deregisters them when the node goes offline.

**Architecture:**
- Routes are part of the capability YAML (per-capability `routes:` block)
- The heartbeat carries routes alongside capabilities
- The relay maintains a `RouteRegistry` that calls `app.add_api_route()` / removes routes
- Three auth modes: `session` (Dashboard cookie), `node_token` (Bearer), `none`
- Routes are served under `/relay/v2/dashboard/api/node-routes/{node_id}/...`

**Tech Stack:** FastAPI, Pydantic, SQLite, httpx (for upstream calls)

---

## Step 1: Add `routes` to capability YAML schema + normalization

**Objective:** Allow `routes:` in capability YAML, validate and normalize it.

**Files:**
- Modify: `nodes/common/capability_loader.py`

**Changes:**
1. Add `routes` to the `allowed` set in `validate_with_schema()` (line 103)
2. Add `routes` to `_NORMALIZED_KEYS` (line 147)
3. In `_normalize_capability()`, forward `routes` from raw to normalized cap dict (after line 337)

**Verification:**
- `validate_profile()` accepts YAML with `routes:` block
- `validate_profile()` rejects unknown keys in routes entries

---

## Step 2: Add `routes` to heartbeat models (server-side)

**Objective:** `HeartbeatRequest` and `NodeHeartbeatRequest` can carry routes.

**Files:**
- Modify: `src/relay_server/models/__init__.py`

**Changes:**
1. Add `RouteDeclaration` model:
```python
class RouteDeclaration(BaseModel):
    path: str = Field(..., min_length=1, max_length=512)
    method: str = Field(..., pattern="^(GET|POST|PUT|DELETE|PATCH)$")
    auth: str = Field("session", pattern="^(session|node_token|none)$")
    upstream: str = Field(..., max_length=2048)
    description: Optional[str] = Field(None, max_length=256)
```
2. Add `routes: Optional[List[RouteDeclaration]] = None` to `HeartbeatRequest` (line 351)
3. Add `routes: Optional[List[RouteDeclaration]] = None` to `NodeHeartbeatRequest` (line 361)

**Verification:**
- `HeartbeatRequest(routes=[{"path": "/test", "method": "GET", "upstream": "http://localhost:8790/test"}])` validates
- `HeartbeatRequest(routes=[{"path": "/test", "method": "INVALID", "upstream": "..."}])` fails

---

## Step 3: Add `routes` to heartbeat processing (server-side core)

**Objective:** `heartbeat()` in `core/discovery.py` stores routes alongside capabilities.

**Files:**
- Modify: `src/relay_server/core/discovery.py`

**Changes:**
1. Add `routes: Optional[List[Dict[str, Any]]] = None` parameter to `heartbeat()` (line 44)
2. Store routes in a new `node_routes` table (or as JSON column in `nodes` table)
3. When `replace_capabilities=True`, also replace routes
4. When node goes offline (`mark_offline_nodes()`), clear its routes

**DB schema (new table):**
```sql
CREATE TABLE IF NOT EXISTS node_routes (
    node_id TEXT NOT NULL,
    path TEXT NOT NULL,
    method TEXT NOT NULL,
    auth TEXT NOT NULL DEFAULT 'session',
    upstream TEXT NOT NULL,
    description TEXT DEFAULT '',
    PRIMARY KEY (node_id, path, method),
    FOREIGN KEY (node_id) REFERENCES nodes(node_id) ON DELETE CASCADE
);
```

**Verification:**
- `heartbeat()` with routes stores them in DB
- `mark_offline_nodes()` clears routes for offline nodes
- Routes are returned with node info

---

## Step 4: RouteRegistry — dynamic FastAPI route registration

**Objective:** New module that registers/deregisters FastAPI routes based on DB state.

**Files:**
- Create: `src/relay_server/core/route_registry.py`

**Content:**
```python
"""Dynamic route registry — registers/deregisters FastAPI routes from node heartbeats."""

import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from relay_server.api.v2.security import require_dashboard_user, check_dashboard_permission
from relay_server.models import AuthContext

logger = logging.getLogger(__name__)

# Prefix for all dynamic node routes
NODE_ROUTES_PREFIX = "/relay/v2/dashboard/api/node-routes"

class RouteRegistry:
    """Manages dynamic FastAPI routes registered by nodes."""

    def __init__(self, app: Any) -> None:
        self._app = app
        self._router = APIRouter()
        self._registered: set[str] = set()  # "node_id:path:method"

    def sync_from_db(self, conn) -> None:
        """Sync routes from DB — add new, remove stale."""
        rows = conn.execute(
            "SELECT node_id, path, method, auth, upstream, description "
            "FROM node_routes"
        ).fetchall()

        current = set()
        for row in rows:
            key = f"{row['node_id']}:{row['path']}:{row['method']}"
            current.add(key)
            if key not in self._registered:
                self._add_route(row)

        # Remove stale
        stale = self._registered - current
        for key in stale:
            self._remove_route(key)

        self._registered = current

    def _add_route(self, row) -> None:
        node_id = row["node_id"]
        path = row["path"]
        method = row["method"].lower()
        upstream = row["upstream"]
        auth = row["auth"]

        full_path = f"{NODE_ROUTES_PREFIX}/{node_id}{path}"

        async def _handler(request: Request, ctx: AuthContext = Depends(require_dashboard_user)):
            if auth == "session":
                check_dashboard_permission(ctx, "dashboard:view")
            # Proxy to upstream
            async with httpx.AsyncClient() as client:
                upstream_url = _resolve_upstream(upstream, request)
                try:
                    resp = await client.request(
                        method=request.method,
                        url=upstream_url,
                        headers=_forward_headers(request),
                        content=await request.body(),
                    )
                    return Response(
                        content=resp.content,
                        status_code=resp.status_code,
                        media_type=resp.headers.get("content-type"),
                    )
                except httpx.RequestError as e:
                    raise HTTPException(status_code=502, detail=f"Upstream error: {e}")

        self._router.add_api_route(
            path=full_path,
            endpoint=_handler,
            methods=[method.upper()],
            include_in_schema=False,
        )
        logger.info("Route registered: %s %s → %s", method.upper(), full_path, upstream)

    def _remove_route(self, key: str) -> None:
        node_id, path, method = key.split(":", 2)
        full_path = f"{NODE_ROUTES_PREFIX}/{node_id}{path}"
        logger.info("Route deregistered: %s %s", method.upper(), full_path)
        # Note: FastAPI doesn't support route removal. We handle this by
        # re-creating the router on each sync cycle.

    def rebuild(self, conn) -> None:
        """Full rebuild — clear and re-register all routes."""
        self._router = APIRouter()
        self._registered.clear()
        self.sync_from_db(conn)

    @property
    def router(self) -> APIRouter:
        return self._router


def _resolve_upstream(upstream: str, request: Request) -> str:
    """Resolve upstream URL, replacing path params from the request."""
    # Simple: just use the upstream as-is for now
    return upstream


def _forward_headers(request: Request) -> dict[str, str]:
    """Forward headers, stripping hop-by-hop headers."""
    headers = dict(request.headers)
    for h in ("host", "content-length", "transfer-encoding", "connection"):
        headers.pop(h, None)
    return headers
```

**Verification:**
- `RouteRegistry.sync_from_db()` registers routes from DB
- Registered routes are reachable under `/relay/v2/dashboard/api/node-routes/{node_id}/...`
- Routes return 502 when upstream is unreachable

---

## Step 5: Wire RouteRegistry into main.py

**Objective:** RouteRegistry is initialized in lifespan and synced periodically.

**Files:**
- Modify: `src/relay_server/main.py`

**Changes:**
1. Import `RouteRegistry`
2. Create registry in `lifespan()` after `init_db()`
3. Register `registry.router` with the app
4. Add route sync to maintenance loop (every 30s or on heartbeat changes)

**Verification:**
- Server starts with RouteRegistry
- Routes are synced from DB on startup

---

## Step 6: Add `routes` to node-cli heartbeat

**Objective:** `RelayClient.heartbeat()` sends routes alongside capabilities.

**Files:**
- Modify: `nodes/common/node_cli.py`

**Changes:**
1. In `RelayClient.heartbeat()` (line 261), after building `cap_status`, build `routes` from the active profile
2. Add `routes` to the heartbeat body

**Verification:**
- `node-cli heartbeat` sends routes in the payload
- Server receives and stores them

---

## Step 7: Tests

**Objective:** Tests for the new feature.

**Files:**
- Create: `tests/test_route_registry.py`

**Test cases:**
1. RouteRegistry syncs routes from DB
2. Registered routes are reachable
3. Routes are deregistered when node goes offline
4. Auth modes work (session, node_token, none)
5. Upstream proxy works (mock httpx)
6. Capability YAML with routes validates
7. Heartbeat with routes stores in DB

**Verification:**
- `pytest tests/test_route_registry.py -v` — all green
- No regression in existing tests

---

## Step 8: Documentation

**Objective:** Document the new feature.

**Files:**
- Modify: `docs/node/capabilities.md` — add `routes:` block documentation
- Modify: `docs/concepts.md` — add Dynamic Node Routes concept
- Modify: `CHANGELOG.md` — add entry

---

## Abschliessende Antwort für das Project Board

Nach der Implementierung:
- **TASKS.md:** T-075 auf `done` setzen
- **DECISIONS.md:** Eintrag mit Datum, Entscheidung (Routes in Capability-YAML, Heartbeat-basiert, 3 Auth-Modi), Begründung
- **PLAN.md:** Phase 15 als `✅ done` markieren
- **IDEAS.md:** "Temporäre Node-Routen" als umgesetzt markieren
