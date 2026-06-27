#!/usr/bin/env python3
"""KI-free Storage Node for AI Relay.

This node has no AI logic. It:
- registers with the relay using storage.* capabilities
- writes/deletes/lists files on the NAS mount
- posts service tasks to the relay when human/AI decisions are needed
"""

import os
import shutil
import sys
import time
from pathlib import Path

import httpx

try:
    from poller import Poller
except ImportError:
    from nodes.common.poller import Poller

STORAGE_PATH = Path(os.environ.get("RELAY_STORAGE_PATH", "/storage"))
QUOTA_THRESHOLD = float(os.environ.get("RELAY_QUOTA_THRESHOLD", "0.85"))


def _ensure_dir(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)


def _artifact_url(artifact_id: str, base_url: str) -> str:
    return f"{base_url}/relay/v2/storage/files/{artifact_id}"


def _meta_url(artifact_id: str, base_url: str) -> str:
    return f"{base_url}/relay/v2/storage/files/{artifact_id}/meta"


def _safe_path(target_path: str | None, base: Path = STORAGE_PATH) -> Path:
    """Resolve a path relative to base and reject path traversal attempts.

    The target may contain subdirectories (e.g. "projects/2026/file.png") but
    must stay inside ``base`` after resolving symlinks and ``..`` segments.
    """
    resolved_base = base.resolve()
    candidate = (resolved_base / (target_path or "")).resolve()
    try:
        candidate.relative_to(resolved_base)
    except ValueError as exc:
        raise ValueError("path traversal attempt") from exc
    return candidate


def handle_archive(stage: dict, meta: dict, token: str) -> dict:
    """Download an artifact from the relay and write it to the NAS."""
    payload = stage.get("payload", {})
    artifact_id = payload.get("artifact_id")
    target_path = payload.get("target_path", artifact_id or "unknown")

    if not artifact_id:
        return {"error": "missing artifact_id in payload"}

    base_url = meta["base_url"]

    r = httpx.get(
        _meta_url(artifact_id, base_url),
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    r.raise_for_status()
    file_meta = r.json()

    r = httpx.get(
        _artifact_url(artifact_id, base_url),
        headers={"Authorization": f"Bearer {token}"},
        timeout=120,
    )
    r.raise_for_status()

    dest = _safe_path(target_path)
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
    """Delete a file from the NAS."""
    payload = stage.get("payload", {})
    target_path = payload.get("target_path")
    if not target_path:
        return {"error": "missing target_path"}

    path = _safe_path(target_path)
    if path.exists():
        path.unlink()
        return {"status": "deleted", "target_path": str(path)}
    return {"status": "not_found", "target_path": str(path)}


def handle_list(stage: dict) -> dict:
    """List files in the NAS storage."""
    prefix = stage.get("payload", {}).get("prefix", "")
    base = _safe_path(prefix)

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
    """Determine storage space status."""
    total, used, free = shutil.disk_usage(STORAGE_PATH)
    ratio = used / total if total else 0

    return {
        "status": "quota",
        "total_bytes": total,
        "used_bytes": used,
        "free_bytes": free,
        "usage_ratio": ratio,
        "threshold": QUOTA_THRESHOLD,
        "threshold_exceeded": ratio > QUOTA_THRESHOLD,
    }


def post_cleanup_request(poller, token: str):
    """If quota is exceeded, post a service task to the relay."""
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
        result = poller.submit_task(task_name, stages, priority=5)
        print(f"posted cleanup request task: {result.get('task', {}).get('task_id')}")
    except Exception as exc:
        print(f"cleanup request failed: {exc}", file=sys.stderr)


def register_handlers(poller):
    """Register storage handlers on the poller and start the loop."""
    STORAGE_PATH.mkdir(parents=True, exist_ok=True)

    def _handle(stage):
        capability = stage.get("capability")
        if capability == "storage.archive":
            return handle_archive(stage, poller.meta, poller.token)
        if capability == "storage.delete":
            return handle_delete(stage)
        if capability == "storage.list":
            return handle_list(stage)
        if capability == "storage.quota":
            post_cleanup_request(poller, poller.token)
            return handle_quota(stage)
        return {"error": f"unknown capability {capability}"}

    for cap in ["storage.archive", "storage.delete", "storage.list", "storage.quota"]:
        poller.register(cap, _handle)

    print(f"storage node {poller.meta['node_id']} started at {STORAGE_PATH}")
    poller.run()


def main():
    poller = Poller()
    register_handlers(poller)


if __name__ == "__main__":
    main()
