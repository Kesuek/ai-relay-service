"""Generischer Worker-Node fuer AI Relay.

Capabilities werden aus einer YAML-Datei geladen und im Heartbeat
an den Server gesendet. Der Worker uebernimmt:
- Heartbeat-Loop mit voller Capability-Liste
- Task-Claiming und -Ausfuehrung
- Graceful Shutdown (SIGTERM/SIGINT)
- Retry mit Exponential Backoff
- SIGHUP-Reload fuer Capabilities
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
from typing import Any, Callable, Optional

import httpx
import typer
import yaml

from nodes.common.capability import (
    CapabilitySet, Capability, load_capabilities_from_yaml,
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
# Retry-Helper
# ---------------------------------------------------------------------------
MAX_RETRIES = 5
INITIAL_BACKOFF = 1.0


def _retry(fn, *args, **kwargs):
    """Rufe ``fn`` mit Exponential-Backoff bei Netzwerkfehlern."""
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
# Worker-Klasse
# ---------------------------------------------------------------------------
class WorkerNode:
    """Generischer Worker-Node mit konfigurierbaren Capabilities."""

    def __init__(
        self,
        name: str,
        base_url: str,
        capabilities_file: Path,
        heartbeat_interval: int = 8,
    ):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.capabilities_file = capabilities_file
        self.heartbeat_interval = heartbeat_interval

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

    # ------------------------------------------------------------------
    # Initialisierung
    # ------------------------------------------------------------------
    def load_capabilities(self) -> None:
        """Capabilities aus YAML-Datei laden."""
        caps = load_capabilities_from_yaml(self.capabilities_file)
        with self._lock:
            self.capabilities = caps
        try:
            self._caps_mtime = os.path.getmtime(self.capabilities_file)
        except OSError:
            self._caps_mtime = 0.0
        log.info("Capabilities geladen: %s", caps.names)

    def reload_capabilities(self, signum=None, frame=None) -> None:
        """SIGHUP-Handler: Capabilities neu laden."""
        log.info("SIGHUP erhalten - lade Capabilities neu")
        try:
            self.load_capabilities()
            self._heartbeat_once()
        except Exception as exc:
            log.error("Fehler beim Reload: %s", exc)

    def register(self) -> bool:
        """Node am Relay-Server registrieren."""
        cap_list = self.capabilities.to_list()
        log.info("Registriere Node '%s' mit %d Capabilities ...", self.name, len(cap_list))

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
            log.error("Registrierung fehlgeschlagen: %s", exc)
            return False

        if not data:
            return False
        self.node_id = data.get("node_id")
        self.token = data.get("token")
        status = data.get("status", "unknown")
        log.info("Registriert: node_id=%s status=%s", self.node_id, status)

        if data.get("registration_secret"):
            self._save_meta(data)

        return True

    def _save_meta(self, data: dict) -> None:
        """Node-Metadaten persistieren."""
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
        """Gespeicherte Metadaten laden (Restart ohne neue Registrierung)."""
        meta_path = BASE_DIR / "worker_meta.json"
        if meta_path.exists():
            return json.loads(meta_path.read_text())
        return None

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------
    def _heartbeat_once(self) -> bool:
        """Ein einzelnes Heartbeat senden."""
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
        """Prueft ob die capabilities.yaml seit dem letzten Laden geaendert wurde."""
        try:
            current_mtime = os.path.getmtime(self.capabilities_file)
        except OSError:
            return
        if current_mtime != self._caps_mtime:
            log.info("Capabilities-Datei geaendert, lade neu")
            self.reload_capabilities()

    def _heartbeat_loop(self) -> None:
        """Hintergrund-Thread: Heartbeat im Intervall senden."""
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

    # ------------------------------------------------------------------
    # Task-Claiming & -Ausfuehrung
    # ------------------------------------------------------------------
    def register_handler(self, capability_name: str, handler: Callable) -> None:
        """Handler fuer eine Capability registrieren."""
        self._handlers[capability_name] = handler
        log.info("Handler registriert: %s", capability_name)

    def _claim_task(self) -> Optional[dict]:
        """Naechsten Task vom Server anfordern."""
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
            log.debug("Kein Task verfuegbar: %s", exc)
            return None

    def _complete_task(self, task_id: str, stage_id: str, result: dict) -> None:
        """Task-Ergebnis an den Server zuruecksenden."""
        try:
            httpx.post(
                f"{self.base_url}/relay/v2/scheduler/stages/{stage_id}/complete",
                headers={"Authorization": f"Bearer {self.token}"},
                json={
                    "node_id": self.node_id,
                    "task_id": task_id,
                    "result": result,
                },
                timeout=self.heartbeat_interval * 3,
            ).raise_for_status()
        except Exception as exc:
            log.error("Task-Abschluss fehlgeschlagen: %s", exc)

    def _execute_stage(self, stage: dict) -> dict:
        """Fuehrt eine Stage aus - delegiert an registrierten Handler."""
        cap = stage.get("capability", "")
        handler = self._handlers.get(cap)
        if handler:
            # Pruefe Payload gegen Input-Schema, falls vorhanden
            cap_obj: Optional[Capability] = self.capabilities.get(cap)
            if cap_obj is not None and cap_obj.input_schema is not None:
                payload = stage.get("payload", {})
                ok, errors = cap_obj.input_schema.validate_payload(payload)
                if not ok:
                    return {"error": "Payload-Validierung fehlgeschlagen", "details": errors}
            return handler(stage)
        return {"error": f"Kein Handler fuer Capability '{cap}'"}

    def _task_loop(self) -> None:
        """Hintergrund-Thread: Tasks claimen und ausfuehren."""
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
                log.error("Task fehlgeschlagen: task=%s error=%s", task_id, exc)
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
        """Schreibt aktuellen Status auf Disk (fuer Monitoring)."""
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

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def _setup_signals(self) -> None:
        """SIGTERM, SIGINT, SIGHUP registrieren."""
        signal.signal(signal.SIGTERM, self._shutdown)
        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGHUP, self.reload_capabilities)

    def _shutdown(self, signum=None, frame=None) -> None:
        """Graceful Shutdown."""
        sig_name = signal.Signals(signum).name if signum else "unknown"
        log.info("Shutdown-Signal empfangen: %s", sig_name)
        self._stop_event.set()

    # ------------------------------------------------------------------
    # Monitoring
    # ------------------------------------------------------------------
    def write_status(self) -> None:
        """Status-Datei einmalig schreiben (zurueckgesetzt fuer Tests)."""
        self._write_status()

    def is_running(self) -> bool:
        """Gibt True zurueck wenn der Worker laeuft."""
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
    # Start
    # ------------------------------------------------------------------
    def start(self) -> None:
        """Worker starten - blockierend bis Shutdown."""
        log.info("=== Worker '%s' startet ===", self.name)

        # Arbeitsverzeichnis sicherstellen
        BASE_DIR.mkdir(parents=True, exist_ok=True)

        self.load_capabilities()

        if not self.register():
            log.error("Registrierung fehlgeschlagen - beende")
            sys.exit(1)

        self._setup_signals()

        hb_thread = threading.Thread(target=self._heartbeat_loop, daemon=True, name="heartbeat")
        task_thread = threading.Thread(target=self._task_loop, daemon=True, name="task-loop")

        hb_thread.start()
        task_thread.start()
        self._threads = [hb_thread, task_thread]

        log.info("Worker '%s' laeuft (node_id=%s)", self.name, self.node_id)

        try:
            while not self._stop_event.is_set():
                self._write_status()
                time.sleep(5)
        except KeyboardInterrupt:
            self._shutdown()

        log.info("Warte auf Threads ...")
        for t in self._threads:
            t.join(timeout=5)

        self._write_status()
        log.info("=== Worker '%s' beendet ===", self.name)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
app = typer.Typer(
    name="relay-worker",
    help="AI-Relay Worker-Node",
    add_completion=False,
)


@app.command("start")
def start(
    name: str = typer.Option("worker-01", "--name", help="Name des Nodes"),
    url: str = typer.Option(
        os.environ.get("RELAY_BASE_URL", "http://localhost:8788"),
        "--url",
        help="Relay-Server URL",
    ),
    caps: Path = typer.Option(
        DEFAULT_CAPS_FILE,
        "--caps",
        help="Pfad zur capabilities.yaml",
    ),
    heartbeat: int = typer.Option(8, "--heartbeat", help="Heartbeat-Intervall in Sekunden"),
):
    """Worker starten und laufen lassen."""
    worker = WorkerNode(
        name=name,
        base_url=url,
        capabilities_file=caps,
        heartbeat_interval=heartbeat,
    )
    worker.start()


@app.command("register")
def register(
    name: str = typer.Option("worker-01", "--name", help="Name des Nodes"),
    url: str = typer.Option(
        os.environ.get("RELAY_BASE_URL", "http://localhost:8788"),
        "--url",
        help="Relay-Server URL",
    ),
    caps: Path = typer.Option(
        DEFAULT_CAPS_FILE,
        "--caps",
        help="Pfad zur capabilities.yaml",
    ),
):
    """Nur registrieren (ohne starten)."""
    worker = WorkerNode(
        name=name,
        base_url=url,
        capabilities_file=caps,
    )
    worker.load_capabilities()
    if worker.register():
        typer.echo(f"Node registriert: {worker.node_id}", err=True)
    else:
        typer.echo("Registrierung fehlgeschlagen", err=True)
        raise typer.Exit(code=1)


@app.command("status")
def status_cmd():
    """Gespeicherten Status anzeigen."""
    if STATUS_FILE.exists():
        typer.echo(STATUS_FILE.read_text())
    else:
        typer.echo(f"Kein Statusfile gefunden unter {STATUS_FILE}", err=True)
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()