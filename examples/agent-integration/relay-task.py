#!/usr/bin/env python3
"""Post a task to the AI Relay service from the local shell."""

import argparse
import json
import sys
from pathlib import Path

import httpx


def load_token_and_url():
    token_path = Path.home() / ".relay" / "ai-relay-agent.token"
    meta_path = Path.home() / ".relay" / "ai-relay-agent.json"
    if not meta_path.exists():
        print(f"metadata missing: {meta_path}", file=sys.stderr)
        sys.exit(1)
    meta = json.loads(meta_path.read_text())
    if token_path.exists():
        token = token_path.read_text().strip()
    else:
        # refresh token
        r = httpx.post(
            f"{meta['base_url']}/relay/v2/auth/status",
            json={"node_id": meta["node_id"], "registration_secret": meta["registration_secret"]},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        token = data["token"]
        token_path.write_text(token)
    return meta["base_url"], token


def main():
    parser = argparse.ArgumentParser(description="Post a task to the AI Relay cluster")
    parser.add_argument("--capability", "-c", default="code", help="required capability")
    parser.add_argument("--title", "-t", default="ad-hoc task", help="task title")
    parser.add_argument("payload", nargs="?", help="JSON payload or literal string")
    args = parser.parse_args()

    base_url, token = load_token_and_url()

    payload = None
    if args.payload:
        try:
            payload = json.loads(args.payload)
        except json.JSONDecodeError:
            payload = {"text": args.payload}

    task = {
        "task_name": args.title,
        "stages": [
            {
                "stage_name": args.capability,
                "capability": args.capability,
                "payload": payload,
            }
        ],
    }

    r = httpx.post(
        f"{base_url}/relay/v2/scheduler/tasks",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=task,
        timeout=30,
    )
    r.raise_for_status()
    print(json.dumps(r.json(), indent=2))


if __name__ == "__main__":
    main()
