#!/usr/bin/env python3
"""KI-lose Storage-Node für AI Relay.

Diese Node hat keine KI-Logik. Sie:
- registriert sich am Relay mit storage.* Capabilities
- schreibt/löscht/listet Dateien auf dem NAS-Mount
- postet Service-Tasks an das Relay, wenn menschliche/KI-Entscheidungen nötig sind
"""

import json
import os
import shutil
import sys
import time
from pathlib import Path

import httpx

from poller import (
    CLAIM_INTERVAL,
    HEARTBEAT_INTERVAL,
    claim,
    complete,
    heartbeat,
    load_meta,
    load_token,
    refresh_runtime_token,
    submit_task,
)

STORAGE_PATH = Path(os.environ.get("RELAY_STORAGE_PATH", "/storage"))
BASE_URL = os.environ.get("RELAY_BASE_URL", "")
NODE_NAME = os.environ.get("RELAY_NODE_NAME", "storage-node")
QUOTA_THRESHOLD = float(os.environ.get("RELAY_QUOTA_THRESHOLD", "0.85"))


def _ensure_dir(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)


def _artifact_url(artifact_id: str, base_url: str) -> str:
    return f"{base_url}/relay/v2/storage/files/{artifact_id}"


def _meta_url(artifact_id: str, base_url: str) -> str:
    return f"{base_url}/relay/v2/storage/files/{artifact_id}/meta"


def handle_archive(stage: dict, meta: dict, token: str) -> dict:
    """Lade Artifact vom Relay herunter und schreibe es aufs NAS."""
    payload = stage.get("payload", {})
    artifact_id = payload.get("artifact_id")
    target_path = payload.get("target_path", artifact_id or "unknown")

    if not artifact_id:
        return {"error": "missing artifact_id in payload"}

    base_url = meta["base_url"]

    # Metadaten lesen
    r = httpx.get(_meta_url(artifact_id, base_url), headers={"Authorization": f"Bearer {token}"}, timeout=10)
    r.raise_for_status()
    file_meta = r.json()

    # Datei herunterladen
    r = httpx.get(_artifact_url(artifact_id, base_url), headers={"Authorization": f"Bearer {token}"}, timeout=120)
    r.raise_for_status()

    dest = STORAGE_PATH / target_path
    _ensure_dir(dest)
    dest.write_bytes(r.content)

    return {
        "status": "archived",
        "artifact_id": artifact_id,
        "target_path": str(dest),
        "name": file_meta.get("name"),
        "size_bytes": file_meta.get("size_bytes"),
    }


def handle_delete(stage: dict) -> dict:
    """Lösche Datei vom NAS."""
    payload = stage.get("payload", {})
    target_path = payload.get("target_path")
    if not target_path:
        return {"error": "missing target_path"}

    path = STORAGE_PATH / target_path
    if path.exists():
        path.unlink()
        return {"status": "deleted", "target_path": str(path)}
    return {"status": "not_found", "target_path": str(path)}


def handle_list(stage: dict) -> dict:
    """Liste Dateien im NAS-Storage auf."""
    prefix = stage.get("payload", {}).get("prefix", "")
    base = STORAGE_PATH / prefix if prefix else STORAGE_PATH

    files = []
    if base.exists():
        for p in base.rglob("*"):
            if p.is_file():
                stat = p.stat()
                files.append({
                    "path": str(p.relative_to(STORAGE_PATH)),
                    "size_bytes": stat.st_size,
                    "modified": stat.st_mtime,
                })

    return {"status": "listed", "count": len(files), "files": files}


def handle_quota(stage: dict) -> dict:
    """Ermittle Speicherplatz-Status."""
    total, used, free = shutil.disk_usage(STORAGE_PATH)
    ratio = used / total if total else 0

    result = {
        "status": "quota",
        "total_bytes": total,
        "used_bytes": used,
        "free_bytes": free,
        "usage_ratio": ratio,
        "threshold": QUOTA_THRESHOLD,
        "threshold_exceeded": ratio > QUOTA_THRESHOLD,
    }
    return result


def post_cleanup_request(meta: dict, token: str):
    """Wenn Quota überschritten ist, poste einen Service-Task ans Relay."""
    try:
        total, used, free = shutil.disk_usage(STORAGE_PATH)
        ratio = used / total if total else 0
        if ratio <= QUOTA_THRESHOLD:
            return

        task_name = f"storage.cleanup_request.{int(time.time())}"
        stages = [
            {
                "stage_name": "decide",
                "capability": "llm.decide_cleanup",
                "payload": {
                    "storage_path": str(STORAGE_PATH),
                    "total_bytes": total,
                    "used_bytes": used,
                    "free_bytes": free,
                    "usage_ratio": ratio,
                },
            }
        ]
        result = submit_task(meta, token, task_name, stages, priority=5)
        print(f"posted cleanup request task: {result.get('task', {}).get('task_id')}")
    except Exception as exc:
        print(f"cleanup request failed: {exc}", file=sys.stderr)


def main():
    STORAGE_PATH.mkdir(parents=True, exist_ok=True)

    meta = load_meta()
    if BASE_URL:
        meta["base_url"] = BASE_URL.rstrip("/")
    token = load_token() or refresh_runtime_token(meta)
    if not token:
        print("no runtime token available", file=sys.stderr)
        sys.exit(1)

    handlers = {
        "storage.archive": lambda stage: handle_archive(stage, meta, token),
        "storage.delete": handle_delete,
        "storage.list": handle_list,
        "storage.quota": handle_quota,
    }

    # Periodische Cleanup-Check (alle 5 Minuten)
    last_cleanup_check = 0

    print(f"storage node {meta['node_id']} started at {STORAGE_PATH}")
    capabilities = [c["name"] for c in meta.get("capabilities", [])]
    print(f"poller started for node {meta['node_id']} with caps {capabilities}")

    last_claim = 0
    while True:
        try:
            current_token = load_token() or token
            if not current_token:
                raise RuntimeError("no token available")
            hb = heartbeat(meta, current_token)
            print(f"heartbeat {hb.get('status')} at {time.strftime('%H:%M:%S')}")

            now = time.time()
            if now - last_cleanup_check > 300:
                post_cleanup_request(meta, current_token)
                last_cleanup_check = now

            if now - last_claim > CLAIM_INTERVAL:
                for cap in capabilities:
                    if cap not in handlers:
                        continue
                    stage = claim(meta, current_token, cap)
                    if stage:
                        print(f"claimed {cap} stage: {stage.get('stage_id')}")
                        try:
                            result = handlers[cap](stage)
                            complete(meta, current_token, stage["stage_id"], result)
                            print(f"completed {stage.get('stage_id')}")
                        except Exception as exc:
                            print(f"handler error for {cap}: {exc}", file=sys.stderr)
                            complete(meta, current_token, stage["stage_id"], {"error": str(exc)})
                        break
                last_claim = now

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
