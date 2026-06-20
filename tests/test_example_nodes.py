"""Integration test for external example nodes.

This test starts the relay server in a subprocess, launches the example
vault and board nodes, approves them, submits a two-stage task, and verifies
that each node claims and completes its matching stage.
"""

import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import httpx
import pytest

REPO = Path(__file__).resolve().parent.parent
PYTHON = REPO / ".venv" / "bin" / "python3"
NODES_DIR = REPO / "examples" / "nodes"

VAULT_NAME = "Vault Example"
BOARD_NAME = "Board Example"


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _wait_for_server(base_url: str, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(f"{base_url}/health", timeout=1.0)
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"Server at {base_url} did not become ready")


def _init_master_secret(env: dict) -> str:
    result = subprocess.run(
        [str(PYTHON), "-m", "relay_server.main", "admin", "init-master"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO),
        check=True,
    )
    for line in result.stdout.splitlines():
        if line.startswith("SECRET: "):
            return line[len("SECRET: ") :].strip()
    raise RuntimeError("Could not extract master secret")


def _register_admin(base_url: str, secret: str) -> str:
    r = httpx.post(
        f"{base_url}/relay/v2/auth/register-admin",
        json={
            "node_name": "Test Admin",
            "bootstrap_secret": secret,
            "capabilities": [{"name": "admin", "version": "1.0.0"}],
        },
    )
    r.raise_for_status()
    return r.json()["token"]


def _approve_nodes(base_url: str, admin_token: str, token_dir: Path) -> dict[str, str]:
    """Find pending example nodes by name, approve them, write tokens, return assigned IDs."""
    ids = {}
    deadline = time.time() + 15.0
    while time.time() < deadline:
        r = httpx.get(
            f"{base_url}/relay/v2/admin/nodes",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        r.raise_for_status()
        pending = [n for n in r.json()["nodes"] if n["status"] == "pending"]
        for node in pending:
            name = node["node_name"]
            caps = []
            if name == VAULT_NAME:
                caps = [{"name": "vault", "version": "1.0.0"}]
            elif name == BOARD_NAME:
                caps = [{"name": "board", "version": "1.0.0"}]
            else:
                continue
            approve = httpx.post(
                f"{base_url}/relay/v2/admin/nodes/{node['node_id']}/approve",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"role": "service", "capabilities": caps},
            )
            approve.raise_for_status()
            token = approve.json()["token"]
            ids[name] = node["node_id"]
            if name == VAULT_NAME:
                (token_dir / "vault.token").write_text(token, encoding="utf-8")
            elif name == BOARD_NAME:
                (token_dir / "board.token").write_text(token, encoding="utf-8")
        if VAULT_NAME in ids and BOARD_NAME in ids:
            return ids
        time.sleep(0.5)
    raise RuntimeError(f"Could not approve example nodes; found: {list(ids.keys())}")


def _submit_task(base_url: str, admin_token: str) -> str:
    r = httpx.post(
        f"{base_url}/relay/v2/scheduler/tasks",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "task_name": "Integration vault+board pipeline",
            "stages": [
                {
                    "stage_name": "store_secret",
                    "capability": "vault",
                    "payload": {"secret_count": 3},
                },
                {
                    "stage_name": "publish_summary",
                    "capability": "board",
                    "payload": {"posts": 1},
                },
            ],
        },
    )
    r.raise_for_status()
    return r.json()["task"]["task_id"]


def _wait_for_task_completion(
    base_url: str, admin_token: str, task_id: str, timeout: float = 30.0
) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = httpx.get(
            f"{base_url}/relay/v2/scheduler/tasks/{task_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        r.raise_for_status()
        data = r.json()
        if data["task"]["status"] == "completed":
            return data
        time.sleep(0.5)
    raise RuntimeError(f"Task {task_id} did not complete in time")


@pytest.fixture
def relay_environment():
    """Provide an isolated relay server with approved example nodes."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db_path = tmp_path / "server.db"
        artifacts_dir = tmp_path / "artifacts"
        token_dir = tmp_path / "tokens"
        token_dir.mkdir()
        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        port = _free_port()
        base_url = f"http://127.0.0.1:{port}"

        env = os.environ.copy()
        env["RELAY_CONFIG_PATH"] = str(tmp_path / "nonexistent_config.yaml")
        env["RELAY_DB_PATH"] = str(db_path)
        env["RELAY_ARTIFACTS_DIR"] = str(artifacts_dir)
        env["RELAY_LOG_LEVEL"] = "info"

        server = None
        vault = None
        board = None
        try:
            server = subprocess.Popen(
                [
                    str(PYTHON),
                    "-m",
                    "relay_server.main",
                    "server",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                stdout=open(log_dir / "server.stdout", "w"),
                stderr=open(log_dir / "server.stderr", "w"),
                env=env,
                cwd=str(REPO),
            )
            _wait_for_server(base_url)

            secret = _init_master_secret(env)

            node_env = env.copy()
            node_env["RELAY_TOKEN_DIR"] = str(token_dir)
            node_env["RELAY_LOG_LEVEL"] = "INFO"

            vault = subprocess.Popen(
                [
                    str(PYTHON),
                    str(NODES_DIR / "vault_node.py"),
                    "--base-url",
                    base_url,
                    "--node-name",
                    VAULT_NAME,
                    "--token-file",
                    str(token_dir / "vault.token"),
                ],
                stdout=open(log_dir / "vault.stdout", "w"),
                stderr=open(log_dir / "vault.stderr", "w"),
                env=node_env,
            )
            board = subprocess.Popen(
                [
                    str(PYTHON),
                    str(NODES_DIR / "board_node.py"),
                    "--base-url",
                    base_url,
                    "--node-name",
                    BOARD_NAME,
                    "--token-file",
                    str(token_dir / "board.token"),
                ],
                stdout=open(log_dir / "board.stdout", "w"),
                stderr=open(log_dir / "board.stderr", "w"),
                env=node_env,
            )

            # Wait long enough for the nodes to register as pending.
            time.sleep(1.0)

            admin_token = _register_admin(base_url, secret)
            assigned_ids = _approve_nodes(base_url, admin_token, token_dir)
            # Give the nodes a moment to pick up the runtime tokens.
            time.sleep(1.0)

            yield {
                "base_url": base_url,
                "secret": secret,
                "admin_token": admin_token,
                "token_dir": token_dir,
                "log_dir": log_dir,
                "vault_id": assigned_ids[VAULT_NAME],
                "board_id": assigned_ids[BOARD_NAME],
            }
        finally:
            for proc in (vault, board, server):
                if proc is not None:
                    try:
                        proc.terminate()
                        proc.wait(timeout=5)
                    except Exception:
                        pass


def test_example_nodes_claim_and_complete(relay_environment):
    base_url = relay_environment["base_url"]
    admin_token = relay_environment["admin_token"]
    vault_id = relay_environment["vault_id"]
    board_id = relay_environment["board_id"]

    task_id = _submit_task(base_url, admin_token)
    task = _wait_for_task_completion(base_url, admin_token, task_id)

    assert task["task"]["status"] == "completed"
    assert len(task["stages"]) == 2

    vault_stage = next(s for s in task["stages"] if s["capability"] == "vault")
    board_stage = next(s for s in task["stages"] if s["capability"] == "board")

    assert vault_stage["status"] == "completed"
    assert vault_stage["claimed_by"] == vault_id
    assert vault_stage["result"]["status"] == "stored"

    assert board_stage["status"] == "completed"
    assert board_stage["claimed_by"] == board_id
    assert board_stage["result"]["status"] == "published"
