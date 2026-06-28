"""Generic worker node for AI Relay.

Capabilities are loaded from a YAML file and sent in the heartbeat
to the server. The worker handles:
- Heartbeat loop with full capability list
- Task claiming and execution
- Graceful shutdown (SIGTERM/SIGINT)
- Retry with exponential backoff
- SIGHUP reload for capabilities
"""

import json
import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import httpx
import typer

from nodes.common.capability import (
    Capability,
    CapabilitySet,
    load_capabilities_from_yaml,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | worker %(node_id)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("worker")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(os.environ.get("RELAY_WORKER_DIR", Path.home() / ".relay" / "worker"))
DEFAULT_CAPS_FILE = BASE_DIR / "capabilities.yaml"
STATUS_FILE = BASE_DIR / "worker_status.json"

# ---------------------------------------------------------------------------
# Retry Helper
# ---------------------------------------------------------------------------
MAX_RETRIES = 5
INITIAL_BACKOFF = 1.0


def _retry(fn, *args, **kwargs):
    """Call ``fn`` with exponential backoff on network errors."""
    backoff = INITIAL_BACKOFF
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except httpx.ConnectError as exc:
            log.warning("Verbindungsfehler (Versuch %d/%d): %s", attempt, MAX_RETRIES, exc)
        except httpx.ReadTimeout as exc:
            log.warning("Timeout (Versuch %d/%d): %s", attempt, MAX_RETRIES, exc)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (429, 500, 502, 503, 504):
                log.warning(
                    "Server-Fehler %d (Versuch %d/%d): %s",
                    exc.response.status_code, attempt, MAX_RETRIES, exc,
                )
            else:
                raise
        if attempt == MAX_RETRIES:
            raise RuntimeError(f"Nach {MAX_RETRIES} Versuchen fehlgeschlagen")
        time.sleep(backoff)
        backoff = min(backoff * 2, 60.0)


# ---------------------------------------------------------------------------
# Worker class
# ---------------------------------------------------------------------------
class WorkerNode:
    """Generic worker node with configurable capabilities."""

    def __init__(
        self,
        name: str,
        base_url: str,
        capabilities_file: Path,
        heartbeat_interval: int = 8,
        task_timeout: int = 600,
    ):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.capabilities_file = capabilities_file
        self.heartbeat_interval = heartbeat_interval
        self.task_timeout = task_timeout

        self.node_id: Optional[str] = None
        self.token: Optional[str] = None
        self.capabilities = CapabilitySet()
        self._caps_mtime: float = 0.0

        self._tasks_completed = 0
        self._tasks_failed = 0
        self._in_flight = 0
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._threads: list[threading.Thread] = []
        self._handlers: dict[str, Callable] = {}

    # ---- Initialization ---------------------------------------------------
    def load_capabilities(self) -> None:
        """Load capabilities from a YAML file."""
        caps = load_capabilities_from_yaml(self.capabilities_file)
        with self._lock:
            self.capabilities = caps
        try:
            self._caps_mtime = os.path.getmtime(self.capabilities_file)
        except OSError:
            self._caps_mtime = 0.0
        log.info("Capabilities loaded: %s", caps.names)

    def reload_capabilities(self, signum=None, frame=None) -> None:
        """Reload handler: reload capabilities."""
        log.info("SIGHUP received, reloading capabilities")
        try:
            self.load_capabilities()
            self._heartbeat_once()
        except Exception as exc:
            log.error("Reload error: %s", exc)

    def register(self) -> bool:
        """Register this node with the relay server."""
        cap_list = self.capabilities.to_list()
        log.info("Registering node '%s' with %d capabilities ...", self.name, len(cap_list))

        def _do_register() -> dict:
            r = httpx.post(
                f"{self.base_url}/relay/v2/auth/register",
                json={
                    "node_name": self.name,
                    "endpoint": None,
                    "capabilities": cap_list,
                    "role": "worker",
                },
                timeout=15,
            )
            r.raise_for_status()
            return r.json()

        try:
            data = _retry(_do_register)
        except Exception as exc:
            log.error("Registration failed: %s", exc)
            return False

        if not data:
            return False
        self.node_id = data.get("node_id")
        self.token = data.get("token")
        status = data.get("status", "unknown")
        log.info("Registered: node_id=%s status=%s", self.node_id, status)

        if data.get("registration_secret"):
            self._save_meta(data)

        return True

    def _save_meta(self, data: dict) -> None:
        """Persist node metadata to disk."""
        meta_path = BASE_DIR / "worker_meta.json"
        meta = {
            "node_id": data.get("node_id"),
            "node_name": self.name,
            "base_url": self.base_url,
            "registration_secret": data.get("registration_secret"),
            "capabilities": self.capabilities.to_list(),
        }
        tmp = meta_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(meta, indent=2, default=str))
        tmp.rename(meta_path)

    def _load_meta(self) -> Optional[dict]:
        """Load persisted metadata (restart without re-registration)."""
        meta_path = BASE_DIR / "worker_meta.json"
        if meta_path.exists():
            return json.loads(meta_path.read_text())
        return None

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------
    def _heartbeat_once(self) -> bool:
        """Send a single heartbeat to the relay."""
        if not self.node_id or not self.token:
            return False

        cap_list = self.capabilities.to_list()

        try:
            r = httpx.post(
                f"{self.base_url}/relay/v2/discovery/worker-heartbeat",
                headers={"Authorization": f"Bearer {self.token}"},
                json={
                    "load": os.getloadavg()[0] if hasattr(os, "getloadavg") else 0.0,
                    "queue_depth": self._in_flight,
                    "capabilities": cap_list,
                },
                timeout=self.heartbeat_interval,
            )
            r.raise_for_status()
            return True
        except Exception as exc:
            log.error("Heartbeat fehlgeschlagen: %s", exc)
            return False

    def _check_caps_changed(self) -> None:
        """Check if capabilities.yaml was modified since last load."""
        try:
            current_mtime = os.path.getmtime(self.capabilities_file)
        except OSError:
            return
        if current_mtime != self._caps_mtime:
            log.info("Capabilities file changed, reloading")
            self.reload_capabilities()

    # ---- Heartbeat Loop ----------------------------------------------------
    def _heartbeat_loop(self) -> None:
        """Send heartbeats at regular intervals."""
        while not self._stop_event.is_set():
            self._check_caps_changed()
            success = self._heartbeat_once()
            with self._lock:
                self._last_hb_ok = success  # type: ignore[attr-defined]
            log.debug("Heartbeat %s", "ok" if success else "failed")

            for _ in range(self.heartbeat_interval):
                if self._stop_event.is_set():
                    break
                time.sleep(1)

    # ---- Task Claiming & Execution -------------------------------------
    def register_handler(self, capability_name: str, handler: Callable) -> None:
        """Register a handler for a specific capability."""
        self._handlers[capability_name] = handler
        log.info("Handler registered: %s", capability_name)

    def _claim_task(self) -> Optional[dict]:
        """Request the next available task from the relay."""
        if not self.node_id or not self.token:
            return None
        cap_list = [c.name for c in self.capabilities.filter(available_only=True)]
        if not cap_list:
            return None
        try:
            r = httpx.post(
                f"{self.base_url}/relay/v2/scheduler/claim",
                headers={"Authorization": f"Bearer {self.token}"},
                json={
                    "capability": None,
                    "capability_type": None,
                },
                timeout=10,
            )
            if r.status_code == 204:
                return None
            r.raise_for_status()
            return r.json().get("stage")
        except Exception as exc:
            log.debug("No task available: %s", exc)
            return None

    def _complete_task(self, task_id: str, stage_id: str, result: dict) -> None:
        """Send the task result back to the relay server."""
        try:
            httpx.post(
                f"{self.base_url}/relay/v2/scheduler/stages/{stage_id}/complete",
                headers={"Authorization": f"Bearer {self.token}"},
                json={
                    "node_id": self.node_id,
                    "task_id": task_id,
                    "result": result,
                },
                timeout=self.task_timeout,
            ).raise_for_status()
        except Exception as exc:
            log.error("Task completion failed: task=%s error=%s", task_id, exc)

    def _execute_stage(self, stage: dict) -> dict:
        """Execute a stage by delegating to the registered handler."""
        cap = stage.get("capability", "")
        handler = self._handlers.get(cap)
        if handler:
            # Check payload against input schema if available
            cap_obj: Optional[Capability] = self.capabilities.get(cap)
            if cap_obj is not None and cap_obj.input_schema is not None:
                payload = stage.get("payload", {})
                ok, errors = cap_obj.input_schema.validate_payload(payload)
                if not ok:
                    return {"error": "Payload validation failed", "details": errors}
            return handler(stage)
        return {"error": f"No handler for capability '{cap}'"}

    def _task_loop(self) -> None:
        """Background thread: claim and execute tasks."""
        while not self._stop_event.is_set():
            with self._lock:
                if self._in_flight > 0:
                    time.sleep(1)
                    continue

            stage = self._claim_task()
            if not stage:
                time.sleep(2)
                continue

            stage_id = stage.get("stage_id", "unknown")
            task_id = stage.get("task_id", "unknown")
            cap = stage.get("capability", "?")
            log.info("Claimed: task=%s stage=%s cap=%s", task_id, stage_id, cap)

            with self._lock:
                self._in_flight += 1

            try:
                result = self._execute_stage(stage)
                self._complete_task(task_id, stage_id, result)
                with self._lock:
                    self._tasks_completed += 1
                log.info("Completed: task=%s stage=%s", task_id, stage_id)
            except Exception as exc:
                log.error("Task failed: task=%s error=%s", task_id, exc)
                self._complete_task(task_id, stage_id, {"error": str(exc)})
                with self._lock:
                    self._tasks_failed += 1
            finally:
                with self._lock:
                    self._in_flight = max(0, self._in_flight - 1)

    # ------------------------------------------------------------------
    # Status-Reporting
    # ------------------------------------------------------------------
    def _write_status(self) -> None:
        """Write current status to disk for monitoring."""
        status = {
            "pid": os.getpid(),
            "node_id": self.node_id,
            "name": self.name,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "capabilities": self.capabilities.to_list(),
            "tasks_completed": self._tasks_completed,
            "tasks_failed": self._tasks_failed,
            "in_flight": self._in_flight,
        }
        tmp = STATUS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(status, indent=2, default=str))
        tmp.rename(STATUS_FILE)

    # ---- Lifecycle ----------------------------------------------------
    def _setup_signals(self) -> None:
        """Register SIGTERM, SIGINT, and SIGHUP handlers."""
        signal.signal(signal.SIGTERM, self._shutdown)
        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGHUP, self.reload_capabilities)

    def _shutdown(self, signum=None, frame=None) -> None:
        """Perform graceful shutdown."""
        sig_name = signal.Signals(signum).name if signum else "unknown"
        log.info("Shutdown signal received: %s", sig_name)
        self._stop_event.set()

    # ------------------------------------------------------------------
    # Monitoring
    # ------------------------------------------------------------------
    def write_status(self) -> None:
        """Write status file once (reset for tests)."""
        self._write_status()

    def is_running(self) -> bool:
        """Return True if the worker is running."""
        return not self._stop_event.is_set()

    @property
    def tasks_completed(self) -> int:
        return self._tasks_completed

    @property
    def tasks_failed(self) -> int:
        return self._tasks_failed

    @property
    def in_flight(self) -> int:
        return self._in_flight

    # ------------------------------------------------------------------
    # ---- Start --------------------------------------------------------------
    def start(self) -> None:
        """Start the worker (blocking until shutdown)."""
        log.info("=== Starting worker '%s' ===", self.name)

        # Ensure working directory exists
        BASE_DIR.mkdir(parents=True, exist_ok=True)

        self.load_capabilities()

        if not self.register():
            log.error("Registration failed, exiting")
            sys.exit(1)

        self._setup_signals()

        hb_thread = threading.Thread(target=self._heartbeat_loop, daemon=True, name="heartbeat")
        task_thread = threading.Thread(target=self._task_loop, daemon=True, name="task-loop")

        hb_thread.start()
        task_thread.start()
        self._threads = [hb_thread, task_thread]

        log.info("Worker '%s' started (node_id=%s)", self.name, self.node_id)

        try:
            while not self._stop_event.is_set():
                self._write_status()
                time.sleep(5)
        except KeyboardInterrupt:
            self._shutdown()

        log.info("Waiting for threads ...")
        for t in self._threads:
            t.join(timeout=5)

        self._write_status()
        log.info("=== Worker '%s' stopped ===", self.name)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
app = typer.Typer(
    name="relay-worker",
    help="AI Relay worker node",
    add_completion=False,
)


@app.command("start")
def start(
    name: str = typer.Option("worker-01", "--name", help="Node name"),
    url: str = typer.Option(
        os.environ.get("RELAY_BASE_URL", "http://localhost:8788"),
        "--url",
        help="Relay server URL",
    ),
    caps: Path = typer.Option(
        DEFAULT_CAPS_FILE,
        "--caps",
        help="Path to capabilities.yaml",
    ),
    heartbeat: int = typer.Option(8, "--heartbeat", help="Heartbeat interval in seconds"),
    task_timeout: int = typer.Option(
        600, "--task-timeout", help="Task completion timeout in seconds"
    ),
):
    """Start the worker and keep it running."""
    worker = WorkerNode(
        name=name,
        base_url=url,
        capabilities_file=caps,
        heartbeat_interval=heartbeat,
        task_timeout=task_timeout,
    )
    worker.start()


@app.command("register")
def register(
    name: str = typer.Option("worker-01", "--name", help="Node name"),
    url: str = typer.Option(
        os.environ.get("RELAY_BASE_URL", "http://localhost:8788"),
        "--url",
        help="Relay server URL",
    ),
    caps: Path = typer.Option(
        DEFAULT_CAPS_FILE,
        "--caps",
        help="Path to capabilities.yaml",
    ),
):
    """Register only (without starting)."""
    worker = WorkerNode(
        name=name,
        base_url=url,
        capabilities_file=caps,
    )
    worker.load_capabilities()
    if worker.register():
        typer.echo(f"Node registered: {worker.node_id}", err=True)
    else:
        typer.echo("Registration failed", err=True)
        raise typer.Exit(code=1)


@app.command("status")
def status_cmd():
    """Display the stored status."""
    if STATUS_FILE.exists():
        typer.echo(STATUS_FILE.read_text())
    else:
        typer.echo(f"No status file found at {STATUS_FILE}", err=True)
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
