"""Example external node that advertises the 'vault' capability.

This node is a standalone process. It does NOT import relay_server internals.
It registers itself in pending state, waits for an admin to approve it and
supply a runtime token, then heartbeats, claims vault stages, and completes them.
"""

from __future__ import annotations

import sys
import time
from typing import Any, Dict

from node_base import run_node

CAPABILITY = "vault"
DEFAULT_NODE_ID = "VT999999"
DEFAULT_NODE_NAME = "Vault Example"


def _do_vault_work(capability: str, node_id: str, stage: Dict[str, Any]) -> Dict[str, Any]:
    """Minimal simulated vault work."""
    payload = stage.get("payload") or {}
    time.sleep(0.5)
    return {
        "capability": capability,
        "stage_id": stage.get("stage_id"),
        "secret_count": payload.get("secret_count", 1),
        "status": "stored",
    }


def main(argv=None):
    return run_node(
        capability=CAPABILITY,
        work_fn=_do_vault_work,
        default_node_id=DEFAULT_NODE_ID,
        default_node_name=DEFAULT_NODE_NAME,
        argv=argv,
    )


if __name__ == "__main__":
    sys.exit(main())
