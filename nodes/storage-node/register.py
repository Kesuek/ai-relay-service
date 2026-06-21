#!/usr/bin/env python3
"""Register the storage node with the relay and write metadata/token files."""

import json
import os
import sys
from pathlib import Path

import httpx

BASE_DIR = Path.home() / ".relay"
META_PATH = BASE_DIR / "ai-relay-agent.json"
TOKEN_PATH = BASE_DIR / "ai-relay-agent.token"

BASE_URL = os.environ.get("RELAY_BASE_URL", "").rstrip("/")
NODE_NAME = os.environ.get("RELAY_NODE_NAME", "storage-node")

CAPABILITIES = [
    {"name": "storage.archive", "version": "1.0.0"},
    {"name": "storage.list", "version": "1.0.0"},
    {"name": "storage.delete", "version": "1.0.0"},
    {"name": "storage.quota", "version": "1.0.0"},
]


def register():
    if not BASE_URL:
        print("RELAY_BASE_URL not set", file=sys.stderr)
        sys.exit(1)

    r = httpx.post(
        f"{BASE_URL}/relay/v2/auth/register",
        json={
            "node_name": NODE_NAME,
            "endpoint": None,
            "capabilities": CAPABILITIES,
            "role": "service",
        },
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()

    BASE_DIR.mkdir(parents=True, exist_ok=True)
    META_PATH.write_text(json.dumps({
        "base_url": BASE_URL,
        "node_id": data["node_id"],
        "node_name": data["node_name"],
        "registration_secret": data["registration_secret"],
        "capabilities": CAPABILITIES,
    }, indent=2))

    if data.get("token"):
        TOKEN_PATH.write_text(data["token"])

    print(f"registered storage node: {data['node_id']}")
    print(f"status: {data['status']}")
    print(f"metadata written to: {META_PATH}")
    if data.get("status") == "pending":
        print("Node is pending approval. Approve it via dashboard or admin API.")


if __name__ == "__main__":
    register()
