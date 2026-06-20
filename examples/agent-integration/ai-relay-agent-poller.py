#!/usr/bin/env python3
"""Minimal AI Relay Agent poller: heartbeat + task claim loop."""

import json
import sys
import time
from pathlib import Path

import httpx

BASE_DIR = Path.home() / ".relay"
META_PATH = BASE_DIR / "ai-relay-agent.json"
TOKEN_PATH = BASE_DIR / "ai-relay-agent.token"
HEARTBEAT_INTERVAL = 8


def load_meta():
    if not META_PATH.exists():
        print(f"metadata missing: {META_PATH}", file=sys.stderr)
        sys.exit(1)
    return json.loads(META_PATH.read_text())


def load_token():
    if TOKEN_PATH.exists():
        return TOKEN_PATH.read_text().strip()
    return None


def refresh_runtime_token(meta):
    url = f"{meta['base_url']}/relay/v2/auth/status"
    r = httpx.post(
        url,
        json={"node_id": meta["node_id"], "registration_secret": meta["registration_secret"]},
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("token_type") == "runtime" and "token" in data:
        TOKEN_PATH.write_text(data["token"])
        return data["token"]
    return None


def heartbeat(meta, token):
    url = f"{meta['base_url']}/relay/v2/discovery/heartbeat"
    caps = meta.get("capabilities", [])
    r = httpx.post(
        url,
        headers={"Authorization": f"Bearer {token}"},
        json={
            "node_id": meta["node_id"],
            "status": "online",
            "load": 0.0,
            "queue_depth": 0,
            "capabilities": caps,
        },
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def claim(meta, token, capability):
    url = f"{meta['base_url']}/relay/v2/scheduler/claim"
    r = httpx.post(
        url,
        headers={"Authorization": f"Bearer {token}"},
        json={"capability": capability},
        timeout=10,
    )
    if r.status_code == 204:
        return None
    r.raise_for_status()
    data = r.json()
    if not data.get("claimed") or not data.get("stage"):
        return None
    return data["stage"]


def execute_task(stage):
    # Placeholder: real execution will be added later.
    return {"status": "ok", "message": f"stage {stage.get('stage_id')} acknowledged"}


def complete(meta, token, task_id, stage_id, result):
    url = f"{meta['base_url']}/relay/v2/scheduler/stages/{stage_id}/complete"
    r = httpx.post(
        url,
        headers={"Authorization": f"Bearer {token}"},
        json={
            "node_id": meta["node_id"],
            "task_id": task_id,
            "result": result,
        },
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def main():
    meta = load_meta()
    token = load_token() or refresh_runtime_token(meta)
    if not token:
        print("no runtime token available", file=sys.stderr)
        sys.exit(1)

    capabilities = [c["name"] for c in meta.get("capabilities", [])]
    print(f"poller started for node {meta['node_id']} with caps {capabilities}")

    last_claim = 0
    while True:
        try:
            token = load_token() or token
            hb = heartbeat(meta, token)
            print(f"heartbeat {hb.get('status')} at {time.strftime('%H:%M:%S')}")

            if time.time() - last_claim > 5:
                for cap in capabilities:
                    stage = claim(meta, token, cap)
                    if stage:
                        print(f"claimed {cap} stage: {stage.get('stage_id')}")
                        result = execute_task(stage)
                        complete(
                            meta,
                            token,
                            stage["task_id"],
                            stage["stage_id"],
                            result,
                        )
                        print(f"completed {stage.get('stage_id')}")
                        break
                last_claim = time.time()

        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                print("token invalid, trying to refresh", file=sys.stderr)
                token = refresh_runtime_token(meta)
                if not token:
                    print("refresh failed, exiting", file=sys.stderr)
                    sys.exit(1)
            else:
                print(f"http error: {exc}", file=sys.stderr)
        except Exception as exc:
            print(f"error: {exc}", file=sys.stderr)

        time.sleep(HEARTBEAT_INTERVAL)


if __name__ == "__main__":
    main()
