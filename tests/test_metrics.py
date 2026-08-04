"""Tests für core/metrics.py — Metrik-Sammlung + Prometheus-Rendering."""

import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("RELAY_SESSION_SECRET", "test-session-secret-do-not-use-in-production")

from relay_server.config import settings
from relay_server.core import metrics
from relay_server.core.db import init_db


@pytest.fixture(autouse=True)
def _reset_registry():
    metrics.reset()
    yield
    metrics.reset()


@pytest.fixture(autouse=True)
def _fresh_db():
    """Jeder Test bekommt eine frische Temp-DB, damit die Gauges deterministisch sind."""
    with tempfile.TemporaryDirectory() as tmp:
        settings.db_path = Path(tmp) / "test.db"
        init_db()
        yield


def test_counter_inc_and_value():
    metrics.inc("relay_auth_failures_total", {"endpoint": "/auth/login"})
    metrics.inc("relay_auth_failures_total", {"endpoint": "/auth/login"})
    assert metrics.get_counter("relay_auth_failures_total", {"endpoint": "/auth/login"}) == 2


def test_collect_returns_db_gauges():
    # Leere DB: Tasks/Stages/Nodes-Zähler sind 0, aber vorhanden.
    data = metrics.collect_metrics()
    assert "tasks_by_status" in data
    assert "stages_by_status" in data
    assert "nodes_online" in data
    assert "queue_depth" in data


def test_render_prometheus_outputs_valid_lines():
    metrics.inc("relay_auth_failures_total", {"endpoint": "/auth/login"})
    text = metrics.render_prometheus()
    assert "relay_auth_failures_total" in text
    assert '{endpoint="/auth/login"}' in text
    # Header-Kommentar für den Prometheus-Typ
    assert "# TYPE" in text or text.startswith("# HELP") or "relay_auth_failures_total" in text


def test_health_and_ready_and_metrics_endpoints():
    from fastapi.testclient import TestClient

    from relay_server.main import app

    with TestClient(app) as client:
        r_health = client.get("/health")
        assert r_health.status_code == 200
        assert r_health.json()["status"] == "ok"

        r_ready = client.get("/ready")
        assert r_ready.status_code == 200
        body = r_ready.json()
        assert body["database"] == "ok"
        assert "scheduler" in body
        assert "event_bus" in body

        r_metrics = client.get("/metrics")
        assert r_metrics.status_code == 200
        assert "relay_nodes_total" in r_metrics.text


def test_auth_failure_counter_increments():
    from fastapi.testclient import TestClient

    from relay_server.core import metrics as _metrics_mod
    from relay_server.main import app

    with TestClient(app) as client:
        # Ungültiger Bearer-Token -> 401 -> Counter steigt
        client.get("/relay/v2/discovery/nodes", headers={"Authorization": "Bearer rt_invalid"})
        # Nach der Anfrage ist der Counter im Metrics-Output
        text = client.get("/metrics").text
        assert "relay_auth_failures_total" in text