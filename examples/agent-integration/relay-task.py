#!/usr/bin/env python3
"""Service client for the AI Relay cluster.

Discovers cluster capabilities, then posts a task that can actually be
fulfilled by an online worker.
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

META_PATH = Path.home() / ".relay" / "ai-relay-agent.json"
TOKEN_PATH = Path.home() / ".relay" / "ai-relay-agent.token"


def load_meta() -> Dict[str, Any]:
    if not META_PATH.exists():
        print(f"metadata missing: {META_PATH}", file=sys.stderr)
        sys.exit(1)
    return json.loads(META_PATH.read_text())


def load_token(meta: Dict[str, Any]) -> str:
    if TOKEN_PATH.exists():
        return TOKEN_PATH.read_text().strip()
    # refresh token
    r = httpx.post(
        f"{meta['base_url']}/relay/v2/auth/status",
        json={"node_id": meta["node_id"], "registration_secret": meta["registration_secret"]},
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("token_type") != "runtime" or "token" not in data:
        print(f"node not approved yet: {data.get('status')}", file=sys.stderr)
        sys.exit(1)
    TOKEN_PATH.write_text(data["token"])
    return data["token"]


def get_headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def list_online_nodes(meta: Dict[str, Any], token: str) -> List[Dict[str, Any]]:
    """Return nodes that are currently online."""
    r = httpx.get(
        f"{meta['base_url']}/relay/v2/discovery/nodes",
        headers=get_headers(token),
        timeout=10,
    )
    r.raise_for_status()
    return [n for n in r.json().get("nodes", []) if n.get("status") == "online"]


def list_capabilities(meta: Dict[str, Any], token: str) -> Dict[str, List[str]]:
    """Map capability names to list of online node IDs that advertise them."""
    nodes = list_online_nodes(meta, token)
    caps: Dict[str, List[str]] = {}
    for node in nodes:
        node_id = node.get("node_id", "unknown")
        for cap in node.get("capabilities", []):
            name = cap.get("name")
            if name:
                caps.setdefault(name, []).append(node_id)
    return caps


def wait_for_capability(
    meta: Dict[str, Any],
    token: str,
    capability: str,
    timeout: float = 60.0,
    poll_interval: float = 2.0,
) -> bool:
    """Wait until at least one online node advertises the requested capability."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        caps = list_capabilities(meta, token)
        if capability in caps:
            return True
        print(f"capability '{capability}' not online yet, waiting {poll_interval}s...")
        time.sleep(poll_interval)
    return False


def submit_task(
    meta: Dict[str, Any],
    token: str,
    task_name: str,
    capability: str,
    payload: Optional[Dict[str, Any]],
    wait: bool = True,
    timeout: float = 300.0,
) -> Dict[str, Any]:
    """Post a task, optionally wait until it completes."""
    task = {
        "task_name": task_name,
        "stages": [
            {
                "stage_name": capability,
                "capability": capability,
                "payload": payload,
            }
        ],
    }
    r = httpx.post(
        f"{meta['base_url']}/relay/v2/scheduler/tasks",
        headers=get_headers(token),
        json=task,
        timeout=30,
    )
    r.raise_for_status()
    task_id = r.json()["task"]["task_id"]
    print(f"task created: {task_id}")

    if not wait:
        return r.json()

    deadline = time.time() + timeout
    while time.time() < deadline:
        r = httpx.get(
            f"{meta['base_url']}/relay/v2/scheduler/tasks/{task_id}",
            headers=get_headers(token),
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        status = data["task"]["status"]
        if status in ("completed", "failed", "timed_out"):
            return data
        time.sleep(2.0)

    raise TimeoutError(f"task {task_id} did not finish within {timeout}s")


def main():
    parser = argparse.ArgumentParser(
        description="Discover relay capabilities and submit tasks that can be fulfilled."
    )
    parser.add_argument("--capability", "-c", default="code", help="required capability")
    parser.add_argument("--title", "-t", default="ad-hoc task", help="task title")
    parser.add_argument("--discover", "-d", action="store_true", help="list online capabilities and exit")
    parser.add_argument("--wait-cap", "-w", action="store_true", help="wait until the capability is online before submitting")
    parser.add_argument("--no-wait", action="store_true", help="do not wait for task completion")
    parser.add_argument("payload", nargs="?", help="JSON payload or literal string")
    args = parser.parse_args()

    meta = load_meta()
    token = load_token(meta)

    if args.discover:
        caps = list_capabilities(meta, token)
        print(json.dumps({"online_capabilities": caps}, indent=2, sort_keys=True))
        return

    if args.wait_cap:
        if not wait_for_capability(meta, token, args.capability):
            print(f"capability '{args.capability}' did not come online in time", file=sys.stderr)
            sys.exit(1)
        print(f"capability '{args.capability}' is online")

    payload = None
    if args.payload:
        try:
            payload = json.loads(args.payload)
        except json.JSONDecodeError:
            payload = {"text": args.payload}

    result = submit_task(
        meta,
        token,
        args.title,
        args.capability,
        payload,
        wait=not args.no_wait,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
