"""Integration test for external example nodes.

This test starts the relay server in a subprocess, launches the example
vault and board nodes, approves them, submits a two-stage task, and verifies
that each node claims and completes its matching stage.
"""

import os
import subprocess
import tempfile
import time
from pathlib import Path

import httpx
import pytest

REPO = Path(__file__).resolve().parent.parent
PYTHON = REPO / ".venv" / "bin" / "python3"
NODES_DIR = REPO / "examples" / "nodes"
PORT = 18789
BASE_URL = f"http://127.0.0.1:{PORT}"


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
        f"{base_url}/relay/v2/auth/register",
        json={
            "node_id": "test-admin",
            "node_name": "Test Admin",
            "bootstrap_secret": secret,
            "capabilities": [{"name": "admin", "version": "1.0.0"}],
            "role": "admin",
        },
    )
    r.raise_for_status()
    return r.json()["token"]


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
                    str(PORT),
                ],
                stdout=open(log_dir / "server.stdout", "w"),
                stderr=open(log_dir / "server.stderr", "w"),
                env=env,
                cwd=str(REPO),
            )
            _wait_for_server(BASE_URL)

            secret = _init_master_secret(env)

            node_env = env.copy()
            node_env["RELAY_TOKEN_DIR"] = str(token_dir)
            node_env["RELAY_LOG_LEVEL"] = "INFO"

            vault = subprocess.Popen(
                [
                    str(PYTHON),
                    str(NODES_DIR / "vault_node.py"),
                    "--base-url",
                    BASE_URL,
                    "--node-id",
                    "vault-node",
                    "--token-file",
                    str(token_dir / "vault-node.token"),
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
                    BASE_URL,
                    "--node-id",
                    "board-node",
                    "--token-file",
                    str(token_dir / "board-node.token"),
                ],
                stdout=open(log_dir / "board.stdout", "w"),
                stderr=open(log_dir / "board.stderr", "w"),
                env=node_env,
            )

            time.sleep(0.5)

            approve_env = env.copy()
            approve_env["RELAY_MASTER_SECRET"] = secret
            approve_env["RELAY_TOKEN_DIR"] = str(token_dir)
            subprocess.run(
                [
                    str(PYTHON),
                    str(NODES_DIR / "approve_nodes.py"),
                    "--base-url",
                    BASE_URL,
                    "--master-secret",
                    secret,
                    "--capabilities",
                    "vault,board",
                    "--token-dir",
                    str(token_dir),
                ],
                check=True,
                env=approve_env,
                cwd=str(REPO),
            )

            yield {
                "base_url": BASE_URL,
                "secret": secret,
                "token_dir": token_dir,
                "log_dir": log_dir,
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
    secret = relay_environment["secret"]

    admin_token = _register_admin(base_url, secret)
    task_id = _submit_task(base_url, admin_token)
    task = _wait_for_task_completion(base_url, admin_token, task_id)

    assert task["task"]["status"] == "completed"
    assert len(task["stages"]) == 2

    vault_stage = next(s for s in task["stages"] if s["capability"] == "vault")
    board_stage = next(s for s in task["stages"] if s["capability"] == "board")

    assert vault_stage["status"] == "completed"
    assert vault_stage["claimed_by"] == "vault-node"
    assert vault_stage["result"]["status"] == "stored"

    assert board_stage["status"] == "completed"
    assert board_stage["claimed_by"] == "board-node"
    assert board_stage["result"]["status"] == "published"
