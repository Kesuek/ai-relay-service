"""Tests for the event bus and SSE stream."""

import asyncio
import json
import os
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Generator

import httpx
import pytest

os.environ["RELAY_DB_PATH"] = ""

from relay_server.config import settings
from relay_server.core.auth import generate_secret, hash_secret
from relay_server.core.db import get_conn, init_db
from relay_server.core.events import EventBus, event_bus


@pytest.fixture(autouse=True)
def fresh_db():
    """Use a temporary database for each test and reset the event bus."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        settings.db_path = db_path
        settings.heartbeat_interval_seconds = 10
        settings.heartbeat_timeout_multiplier = 2
        settings.claim_ttl_seconds = 60
        init_db()
        event_bus.clear()
        yield
        event_bus.clear()


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


@pytest.fixture(scope="module")
def live_server() -> Generator[tuple[str, str], None, None]:
    """Start a real relay server in a subprocess for SSE integration tests."""
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "live.db"
    config_path = Path(tmp) / "config.yaml"
    config_path.write_text(f"db_path: {db_path}\nlog_level: warning\n")
    settings.db_path = db_path
    init_db()

    secret = generate_secret("adm_")
    conn = get_conn()
    conn.execute(
        "INSERT INTO admin_seeds (seed_id, seed_hash, role, created_at) VALUES (?, ?, ?, ?)",
        ("master", hash_secret(secret), "admin", "2026-01-01T00:00:00+00:00"),
    )
    conn.commit()
    conn.close()

    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    repo = Path(__file__).resolve().parent.parent
    python = repo / ".venv" / "bin" / "python3"
    env = os.environ.copy()
    env["RELAY_CONFIG_PATH"] = str(config_path)
    env["RELAY_DB_PATH"] = str(db_path)
    env["RELAY_LOG_LEVEL"] = "warning"

    proc = subprocess.Popen(
        [
            str(python),
            "-m",
            "uvicorn",
            "relay_server.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(repo),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    deadline = time.time() + 15.0
    last_error = None
    while time.time() < deadline:
        try:
            r = httpx.get(f"{base_url}/health", timeout=1.0)
            if r.status_code == 200:
                break
        except Exception as e:
            last_error = e
        time.sleep(0.1)
    else:
        proc.terminate()
        proc.wait(timeout=5.0)
        raise RuntimeError(f"Server failed to start: {last_error}")

    try:
        yield base_url, secret
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5.0)


def _http_admin_token(base_url: str, secret: str, node_id: str = "admin-test") -> str:
    r = httpx.post(
        f"{base_url}/relay/v2/auth/register",
        json={
            "node_id": node_id,
            "node_name": node_id,
            "bootstrap_secret": secret,
            "capabilities": [{"name": "admin", "version": "1.0.0"}],
            "role": "admin",
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _http_worker_token(base_url: str, admin_token: str, node_id: str, capabilities: list) -> str:
    r = httpx.post(
        f"{base_url}/relay/v2/auth/register",
        json={
            "node_id": node_id,
            "node_name": node_id,
            "endpoint": "http://localhost:9001",
            "capabilities": capabilities,
            "role": "service",
        },
    )
    assert r.status_code == 200, r.text
    r2 = httpx.post(
        f"{base_url}/relay/v2/admin/nodes/{node_id}/approve",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"role": "service", "capabilities": capabilities},
    )
    assert r2.status_code == 200, r2.text
    return r2.json()["token"]


def _wait_for_subscribers(base_url: str, count: int, timeout: float = 3.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(f"{base_url}/health", timeout=1.0)
            if r.json().get("event_subscribers", 0) >= count:
                return
        except Exception:
            pass
        time.sleep(0.05)
    raise AssertionError(f"Expected {count} subscriber(s) on server")


@pytest.mark.asyncio
async def test_event_bus_subscribe_and_publish():
    received: list[dict] = []

    async def consumer():
        async for message in event_bus.subscribe("sub-1"):
            data = json.loads(message.split("data: ", 1)[1].split("\n\n", 1)[0])
            received.append(data)
            if len(received) == 2:
                break

    task = asyncio.create_task(consumer())
    for _ in range(100):
        if event_bus.subscriber_count() == 1:
            break
        await asyncio.sleep(0.01)
    assert event_bus.subscriber_count() == 1

    await event_bus.publish("task_created", {"task_id": "t1"})
    await event_bus.publish("presence_changed", {"node_id": "n1"})

    await asyncio.wait_for(task, timeout=2.0)

    assert len(received) == 2
    assert received[0]["type"] == "task_created"
    assert received[0]["payload"] == {"task_id": "t1"}
    assert received[1]["type"] == "presence_changed"


@pytest.mark.asyncio
async def test_event_bus_unique_subscriber_ids_per_node():
    """Multiple streams for the same node must not overwrite each other."""
    received_a: list[dict] = []
    received_b: list[dict] = []

    async def consumer_a():
        async for message in event_bus.subscribe(node_id="shared-node"):
            data = json.loads(message.split("data: ", 1)[1].split("\n\n", 1)[0])
            received_a.append(data)
            if len(received_a) == 1:
                break

    async def consumer_b():
        async for message in event_bus.subscribe(node_id="shared-node"):
            data = json.loads(message.split("data: ", 1)[1].split("\n\n", 1)[0])
            received_b.append(data)
            if len(received_b) == 1:
                break

    task_a = asyncio.create_task(consumer_a())
    task_b = asyncio.create_task(consumer_b())
    for _ in range(100):
        if event_bus.subscriber_count() == 2:
            break
        await asyncio.sleep(0.01)
    assert event_bus.subscriber_count() == 2

    await event_bus.publish("task_created", {"task_id": "t1"})

    await asyncio.wait_for(task_a, timeout=2.0)
    await asyncio.wait_for(task_b, timeout=2.0)

    assert len(received_a) == 1
    assert len(received_b) == 1
    assert received_a[0]["type"] == "task_created"
    assert received_b[0]["type"] == "task_created"


@pytest.mark.asyncio
async def test_event_bus_publish_sync_drop_counter():
    """Drops triggered by a full queue are counted in publish_sync too."""
    received: list[dict] = []

    async def slow_consumer():
        async for message in event_bus.subscribe():
            data = json.loads(message.split("data: ", 1)[1].split("\n\n", 1)[0])
            received.append(data)
            await asyncio.sleep(0.1)
            if len(received) == 1:
                break

    task = asyncio.create_task(slow_consumer())
    for _ in range(100):
        if event_bus.subscriber_count() == 1:
            break
        await asyncio.sleep(0.01)

    # Fill and overflow the queue from a synchronous context.
    for i in range(EventBus.DEFAULT_QUEUE_SIZE + 5):
        event_bus.publish_sync("task_created", {"task_id": f"t{i}"})

    await asyncio.wait_for(task, timeout=5.0)
    assert len(received) == 1
    # At least the overflowed events should be counted as dropped.
    sub = list(event_bus._subscribers.values())[0]
    assert sub.dropped >= 5


@pytest.mark.asyncio
async def test_event_bus_type_filter():
    received: list[dict] = []

    async def consumer():
        async for message in event_bus.subscribe(node_id="sub-2", event_types={"stage_claimed"}):
            data = json.loads(message.split("data: ", 1)[1].split("\n\n", 1)[0])
            received.append(data)
            if len(received) == 1:
                break

    task = asyncio.create_task(consumer())
    for _ in range(100):
        if event_bus.subscriber_count() == 1:
            break
        await asyncio.sleep(0.01)

    await event_bus.publish("task_created", {"task_id": "t1"})
    await event_bus.publish("stage_claimed", {"stage_id": "s1"})

    await asyncio.wait_for(task, timeout=2.0)

    assert len(received) == 1
    assert received[0]["type"] == "stage_claimed"
    assert received[0]["payload"]["stage_id"] == "s1"


def test_sse_stream_receives_event(live_server):
    base_url, secret = live_server
    admin_token = _http_admin_token(base_url, secret, node_id="admin-sse-receive")
    worker_token = _http_worker_token(
        base_url, admin_token, "worker-sse", [{"name": "board", "version": "1.0"}]
    )

    received: list[str] = []

    def reader():
        with httpx.Client(timeout=None) as client:
            with client.stream(
                "GET",
                f"{base_url}/relay/v2/events/stream",
                params={"node": "worker-sse", "types": "presence_changed"},
                headers={"Authorization": f"Bearer {worker_token}"},
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    received.append(line)
                    if line == "":
                        return

    t = threading.Thread(target=reader)
    t.start()
    _wait_for_subscribers(base_url, 1)

    r = httpx.post(
        f"{base_url}/relay/v2/presence/update",
        headers={"Authorization": f"Bearer {worker_token}"},
        json={"status": "busy", "mood": "focused"},
    )
    assert r.status_code == 200, r.text

    t.join(timeout=5.0)
    assert not t.is_alive(), "SSE reader did not receive event"

    event_types = [line for line in received if line.startswith("event: ")]
    assert any("presence_changed" in line for line in event_types)


def test_sse_stream_filters_by_type(live_server):
    base_url, secret = live_server
    admin_token = _http_admin_token(base_url, secret, node_id="admin-sse-filter")
    worker_token = _http_worker_token(
        base_url, admin_token, "worker-filter", [{"name": "board", "version": "1.0"}]
    )

    received: list[str] = []

    def reader():
        with httpx.Client(timeout=None) as client:
            with client.stream(
                "GET",
                f"{base_url}/relay/v2/events/stream",
                params={"node": "worker-filter", "types": "task_created"},
                headers={"Authorization": f"Bearer {worker_token}"},
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    received.append(line)
                    if line == "":
                        return

    t = threading.Thread(target=reader)
    t.start()
    _wait_for_subscribers(base_url, 1)

    # This event should be filtered out.
    r = httpx.post(
        f"{base_url}/relay/v2/presence/update",
        headers={"Authorization": f"Bearer {worker_token}"},
        json={"status": "idle"},
    )
    assert r.status_code == 200, r.text

    # Give the server a moment to publish the filtered event.
    time.sleep(0.2)

    # This event should be delivered.
    r = httpx.post(
        f"{base_url}/relay/v2/scheduler/tasks",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "task_name": "Filtered task",
            "stages": [{"stage_name": "s1", "capability": "board"}],
        },
    )
    assert r.status_code == 200, r.text

    t.join(timeout=5.0)
    assert not t.is_alive(), "SSE reader did not receive event"

    event_types = [line for line in received if line.startswith("event: ")]
    assert event_types == ["event: task_created"]


def test_sse_forbidden_for_other_node(live_server):
    base_url, secret = live_server
    admin_token = _http_admin_token(base_url, secret, node_id="admin-sse-forbidden")
    worker_token = _http_worker_token(
        base_url, admin_token, "worker-other", [{"name": "board", "version": "1.0"}]
    )

    r = httpx.get(
        f"{base_url}/relay/v2/events/stream",
        params={"node": "someone-else"},
        headers={"Authorization": f"Bearer {worker_token}"},
    )
    assert r.status_code == 403


def test_sse_rejects_unknown_event_types(live_server):
    base_url, secret = live_server
    admin_token = _http_admin_token(base_url, secret, node_id="admin-sse-types")
    worker_token = _http_worker_token(
        base_url, admin_token, "worker-types", [{"name": "board", "version": "1.0"}]
    )

    r = httpx.get(
        f"{base_url}/relay/v2/events/stream",
        params={"node": "worker-types", "types": "task_created,not_a_real_event"},
        headers={"Authorization": f"Bearer {worker_token}"},
    )
    assert r.status_code == 400
    assert "not_a_real_event" in r.text
