"""Manual end-to-end test for example nodes."""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

VAULT_TOKEN_FILE = "vault.token"
BOARD_TOKEN_FILE = "board.token"

PORT = 18788
BASE_URL = f"http://127.0.0.1:{PORT}"
REPO = Path("/home/felix/projects/ai-relay-service")
PYTHON = REPO / ".venv" / "bin" / "python3"
NODES_DIR = REPO / "examples" / "nodes"
VAULT_NAME = "Vault Example"
BOARD_NAME = "Board Example"


def run(*args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, text=True, **kwargs)


def run_bg(*args, **kwargs):
    return subprocess.Popen(
        args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **kwargs
    )


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db_path = tmp_path / "server.db"
        artifacts_dir = tmp_path / "artifacts"
        token_dir = tmp_path / "tokens"
        token_dir.mkdir()

        env = os.environ.copy()
        env["RELAY_CONFIG_PATH"] = "/tmp/relay_test_config_does_not_exist.yaml"
        env["RELAY_DB_PATH"] = str(db_path)
        env["RELAY_ARTIFACTS_DIR"] = str(artifacts_dir)
        env["RELAY_LOG_LEVEL"] = "info"

        print("Starting relay server...")
        server = run_bg(
            str(PYTHON),
            "-m",
            "relay_server.main",
            "server",
            "--host",
            "127.0.0.1",
            "--port",
            str(PORT),
            env=env,
            cwd=str(REPO),
        )

        vault = None
        board = None
        try:
            # Wait for server ready
            for i in range(30):
                try:
                    import httpx

                    r = httpx.get(f"{BASE_URL}/health", timeout=1.0)
                    if r.status_code == 200:
                        print("Server ready.")
                        break
                except Exception:
                    pass
                time.sleep(0.5)
            else:
                print("Server failed to start")
                print(server.stderr.read(4096))
                return 1

            # Initialize master seed
            print("Initializing master seed...")
            result = run(
                str(PYTHON),
                "-m",
                "relay_server.main",
                "admin",
                "init-master",
                env=env,
                cwd=str(REPO),
            )
            output = result.stdout
            print(output)
            secret = None
            for line in output.splitlines():
                if line.startswith("SECRET: "):
                    secret = line[len("SECRET: ") :].strip()
                    break
            if not secret:
                print("Could not extract master secret")
                return 1
            print(f"Master secret: {secret[:12]}...")

            # Start nodes
            print("Starting vault node...")
            vault_env = env.copy()
            vault_env["RELAY_TOKEN_DIR"] = str(token_dir)
            vault_env["RELAY_LOG_LEVEL"] = "INFO"
            vault = run_bg(
                str(PYTHON),
                str(NODES_DIR / "vault_node.py"),
                "--base-url",
                BASE_URL,
                "--node-name",
                VAULT_NAME,
                "--token-file",
                str(token_dir / VAULT_TOKEN_FILE),
                env=vault_env,
            )

            print("Starting board node...")
            board_env = env.copy()
            board_env["RELAY_TOKEN_DIR"] = str(token_dir)
            board_env["RELAY_LOG_LEVEL"] = "INFO"
            board = run_bg(
                str(PYTHON),
                str(NODES_DIR / "board_node.py"),
                "--base-url",
                BASE_URL,
                "--node-name",
                BOARD_NAME,
                "--token-file",
                str(token_dir / BOARD_TOKEN_FILE),
                env=board_env,
            )

            time.sleep(1)

            print(f"Vault alive: {vault.poll() is None}, Board alive: {board.poll() is None}")
            if vault.poll() is not None:
                print("Vault exited early. stdout:", vault.stdout.read())
                print("Vault stderr:", vault.stderr.read())
            if board.poll() is not None:
                print("Board exited early. stdout:", board.stdout.read())
                print("Board stderr:", board.stderr.read())

            # Approve nodes
            print("Approving nodes...")
            approve_env = env.copy()
            approve_env["RELAY_MASTER_SECRET"] = secret
            approve_env["RELAY_TOKEN_DIR"] = str(token_dir)
            approve_result = subprocess.run(
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
                capture_output=True,
                text=True,
                env=approve_env,
                cwd=str(REPO),
            )
            print("approve stdout:", approve_result.stdout)
            print("approve stderr:", approve_result.stderr)
            approve_result.check_returncode()

            for i in range(20):
                if (token_dir / VAULT_TOKEN_FILE).exists() and (
                    token_dir / BOARD_TOKEN_FILE
                ).exists():
                    print("Runtime tokens written.")
                    break
                time.sleep(0.5)
            else:
                print("Tokens not written")
                return 1

            # Register admin and submit task
            print("Registering admin...")
            import httpx

            r = httpx.post(
                f"{BASE_URL}/relay/v2/auth/register-admin",
                json={
                    "node_name": "Demo Admin",
                    "bootstrap_secret": secret,
                    "capabilities": [{"name": "admin", "version": "1.0.0"}],
                },
            )
            print(f"Admin register: {r.status_code} {r.json()}")
            admin_token = r.json()["token"]

            print("Submitting task...")
            r = httpx.post(
                f"{BASE_URL}/relay/v2/scheduler/tasks",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={
                    "task_name": "Demo vault+board pipeline",
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
            print(f"Task create: {r.status_code}")
            task_id = r.json()["task"]["task_id"]

            print("Waiting for task completion...")
            for i in range(30):
                r = httpx.get(
                    f"{BASE_URL}/relay/v2/scheduler/tasks/{task_id}",
                    headers={"Authorization": f"Bearer {admin_token}"},
                )
                status = r.json()["task"]["status"]
                print(f"  Task status: {status}")
                if status == "completed":
                    print("Task completed!")
                    print(json.dumps(r.json(), indent=2))
                    break
                time.sleep(1)
            else:
                print("Task did not complete in time")
                return 1

            print("\n--- Vault node stdout ---")
            vault.terminate()
            vault_stdout, vault_stderr = vault.communicate(timeout=5)
            print(vault_stdout)
            print(vault_stderr)

            print("\n--- Board node stdout ---")
            board.terminate()
            board_stdout, board_stderr = board.communicate(timeout=5)
            print(board_stdout)
            print(board_stderr)

        finally:
            print("\nCleaning up...")
            for p in [vault, board, server]:
                if p is not None:
                    try:
                        p.terminate()
                        p.wait(timeout=5)
                    except Exception:
                        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
