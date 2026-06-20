"""Example external node that advertises the 'board' capability.

This node is a standalone process. It does NOT import relay_server internals.
It registers itself in pending state, waits for an admin to approve it and
supply a runtime token, then heartbeats, claims board stages, and completes them.
"""

from __future__ import annotations

import sys
import time
from typing import Any, Dict

from node_base import run_node

CAPABILITY = "board"
DEFAULT_NODE_ID = "board-node"
DEFAULT_NODE_NAME = "Board Node"


def _do_board_work(capability: str, node_id: str, stage: Dict[str, Any]) -> Dict[str, Any]:
    """Minimal simulated board work."""
    payload = stage.get("payload") or {}
    time.sleep(0.3)
    return {
        "capability": capability,
        "stage_id": stage.get("stage_id"),
        "posts_created": payload.get("posts", 1),
        "status": "published",
    }


def main(argv=None):
    return run_node(
        capability=CAPABILITY,
        work_fn=_do_board_work,
        default_node_id=DEFAULT_NODE_ID,
        default_node_name=DEFAULT_NODE_NAME,
        argv=argv,
    )


if __name__ == "__main__":
    sys.exit(main())
