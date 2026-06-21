"""Generic Relay poller for KI-lose service nodes."""

import json
import os
import sys
import time
from pathlib import Path

import httpx

HEARTBEAT_INTERVAL = int(os.environ.get("RELAY_POLL_INTERVAL", "8"))
CLAIM_INTERVAL = 5


def load_meta():
    path = Path.home() / ".relay" / "ai-relay-agent.json"
    if not path.exists():
        print(f"metadata missing: {path}", file=sys.stderr)
        sys.exit(1)
    return json.loads(path.read_text())


def load_token():
    path = Path.home() / ".relay" / "ai-relay-agent.token"
    if path.exists():
        return path.read_text().strip()
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
        token_path = Path.home() / ".relay" / "ai-relay-agent.token"
        token_path.write_text(data["token"])
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


def complete(meta, token, stage_id, result):
    url = f"{meta['base_url']}/relay/v2/scheduler/stages/{stage_id}/complete"
    r = httpx.post(
        url,
        headers={"Authorization": f"Bearer {token}"},
        json={"result": result},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def submit_task(meta, token, task_name, stages, priority=0):
    url = f"{meta['base_url']}/relay/v2/scheduler/tasks"
    r = httpx.post(
        url,
        headers={"Authorization": f"Bearer {token}"},
        json={
            "task_name": task_name,
            "stages": stages,
            "priority": priority,
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def poller(meta, token, handlers):
    """Run heartbeat + claim loop with per-capability handlers.

    handlers: dict mapping capability_name -> callable(stage) -> result dict
    """
    capabilities = [c["name"] for c in meta.get("capabilities", [])]
    print(f"poller started for node {meta['node_id']} with caps {capabilities}")

    last_claim = 0
    while True:
        try:
            token = load_token() or token
            hb = heartbeat(meta, token)
            print(f"heartbeat {hb.get('status')} at {time.strftime('%H:%M:%S')}")

            if time.time() - last_claim > CLAIM_INTERVAL:
                for cap in capabilities:
                    if cap not in handlers:
                        continue
                    stage = claim(meta, token, cap)
                    if stage:
                        print(f"claimed {cap} stage: {stage.get('stage_id')}")
                        try:
                            result = handlers[cap](stage)
                            complete(meta, token, stage["stage_id"], result)
                            print(f"completed {stage.get('stage_id')}")
                        except Exception as exc:
                            print(f"handler error for {cap}: {exc}", file=sys.stderr)
                            complete(meta, token, stage["stage_id"], {"error": str(exc)})
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
