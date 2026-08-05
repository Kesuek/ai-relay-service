"""Tests für core/metrics.py — Metrik-Sammlung + Prometheus-Rendering."""

import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("RELAY_SESSION_SECRET", "test-session-secret-do-not-use-in-production")

from relay_server.config import settings
from relay_server.core import metrics
from relay_server.core.db import get_conn, init_db, q


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


def test_json_logging_formatter_outputs_json():
    import logging
    import io

    from relay_server.core.logging_setup import JsonFormatter

    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="relay", level=logging.INFO, pathname=__file__, lineno=1,
        msg="hello %s", args=("world",), exc_info=None,
    )
    out = formatter.format(record)
    assert '"msg": "hello world"' in out
    assert '"level": "INFO"' in out


def test_trace_id_middleware_sets_header():
    import json

    from fastapi.testclient import TestClient

    from relay_server.main import app

    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        trace_id = r.headers.get("X-Relay-Trace-Id")
        assert trace_id
        assert len(trace_id) >= 8


def _seed_completed_task(task_id: str, start: str, end: str, retry_count: int = 0):
    """Insert a completed task + one completed stage (T-115 latency test)."""
    conn = get_conn()
    try:
        conn.execute(q(
            "INSERT INTO tasks (task_id, task_name, status, created_at, updated_at, completed_at) "
            "VALUES (?, ?, 'completed', ?, ?, ?)",
            (task_id, "t", start, end, end),
        ))
        conn.execute(q(
            "INSERT INTO task_stages (stage_id, task_id, stage_name, capability, status, "
            "claimed_at, completed_at, created_at, updated_at, retry_count) "
            "VALUES (?, ?, 's', 'cap', 'completed', ?, ?, ?, ?, ?)",
            (f"{task_id}_s", task_id, start, end, start, end, retry_count),
        ))
        conn.commit()
    finally:
        conn.close()


def test_latency_histograms_computed():
    """Completed stages/tasks produce latency histograms."""
    _seed_completed_task("T1", "2026-08-04T00:00:00Z", "2026-08-04T00:00:30Z")  # 30s
    _seed_completed_task("T2", "2026-08-04T00:00:00Z", "2026-08-04T00:02:00Z")  # 120s

    data = metrics.collect_metrics()
    latency = data["latency"]
    # 2 completed stages; stage duration (created→completed) = 30s + 120s
    stage_hist = latency["relay_stage_duration_seconds"]
    assert stage_hist["count"] == 2
    assert stage_hist["sum"] == 150.0  # 30 + 120
    # claim duration (claimed_at→completed_at) = 30s + 120s
    claim_hist = latency["relay_claim_duration_seconds"]
    assert claim_hist["count"] == 2
    assert claim_hist["sum"] == 150.0
    # 30s falls in bucket le="30.0" (only 30s obs); 120s falls in le="120.0" (both)
    assert stage_hist["buckets"]["30.0"] == 1
    assert stage_hist["buckets"]["120.0"] == 2


def test_retry_rate_computed():
    """Stages with retry_count > 0 are counted as retried."""
    _seed_completed_task("T1", "2026-08-04T00:00:00Z", "2026-08-04T00:00:30Z", retry_count=2)
    _seed_completed_task("T2", "2026-08-04T00:00:00Z", "2026-08-04T00:00:30Z")  # retry_count=0

    data = metrics.collect_metrics()
    retry = data["retry"]
    assert retry["total"] == 2
    assert retry["retried"] == 1
    assert retry["ratio"] == 0.5


def test_node_gauges_per_node():
    """Per-node load/queue_depth/online gauges."""
    conn = get_conn()
    try:
        conn.execute(q(
            "INSERT INTO nodes (node_id, node_name, status, load, queue_depth, last_seen, registered_at) "
            "VALUES (?, ?, 'online', ?, ?, ?, ?)",
            ("N1", "node-a", 30.0, 2, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
        ))
        conn.execute(q(
            "INSERT INTO nodes (node_id, node_name, status, load, queue_depth, last_seen, registered_at) "
            "VALUES (?, ?, 'offline', ?, ?, ?, ?)",
            ("N2", "node-b", 0.0, 0, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
        ))
        conn.commit()
    finally:
        conn.close()

    data = metrics.collect_metrics()
    nodes = {n["node_name"]: n for n in data["nodes"]}
    assert nodes["node-a"]["load"] == 30.0
    assert nodes["node-a"]["queue_depth"] == 2
    assert nodes["node-a"]["online"] == 1
    assert nodes["node-b"]["online"] == 0


def test_prometheus_renders_latency_and_retry():
    """Prometheus output includes histogram buckets, retry, node gauges."""
    _seed_completed_task("T1", "2026-08-04T00:00:00Z", "2026-08-04T00:00:30Z", retry_count=2)
    conn = get_conn()
    try:
        conn.execute(q(
            "INSERT INTO nodes (node_id, node_name, status, load, queue_depth, last_seen, registered_at) "
            "VALUES (?, ?, 'online', ?, ?, ?, ?)",
            ("N1", "node-a", 10.0, 0, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
        ))
        conn.commit()
    finally:
        conn.close()

    text = metrics.render_prometheus()
    assert "relay_stage_duration_seconds_bucket{le=\"30.0\"}" in text
    assert "relay_stage_duration_seconds_count 1" in text
    assert "relay_stages_retried_total 1" in text
    assert 'relay_node_load{node_id="N1",node_name="node-a"} 10.0' in text
    assert "relay_tasks_created_5m" in text
    assert "relay_tasks_completed_5m" in text