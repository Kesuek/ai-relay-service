#!/usr/bin/env python3
"""KI-capable AI Relay agent poller.

This poller uses nodes/common/poller.py for authentication, heartbeats,
claiming, and completion. When it claims a stage it delegates the payload to the
local Hermes AI. The AI decides which local tools to run and how to combine
them.

The node is KI-capable, so it must not hard-code tool calls. Tool availability,
environment paths, and prompt interpretation live inside the local Hermes
session.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

# Import the generic poller from the relay repo.  The path must be absolute
# so the systemd unit can start this script from any working directory.
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "nodes" / "common"))

import poller  # noqa: E402


def run_local_hermes(prompt: str, toolsets=None) -> dict:
    """Delegate a prompt to the local Hermes AI."""
    toolsets = toolsets or os.environ.get("HERMES_TOOLSETS", "terminal,file,web,image_gen")
    cmd = [
        "hermes",
        "-z", prompt,
        "-t", toolsets,
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=600,
        env=os.environ.copy(),
    )
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
    }


def handle_stage(stage: dict) -> dict:
    payload = stage.get("payload") or {}
    prompt = payload.get("prompt") or payload.get("task_description") or json.dumps(payload)

    ai_result = run_local_hermes(prompt)

    return {
        "status": "ok",
        "result": ai_result,
    }


def main():
    p = poller.Poller()
    p.register("agent.task", handle_stage)
    p.run()


if __name__ == "__main__":
    main()
