#!/usr/bin/env python3
"""Container healthcheck for the node base image (T-119).

Reads the daemon's status file (``~/.relay/worker_status.json``) and
exits 0 when the daemon is running and recently heartbeatet, 1 otherwise.
The status file is written by ``node-daemon`` on every heartbeat.

We do NOT use a TCP probe — the node does not listen on any port. The
status file is the single source of truth for "is the daemon alive?".
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

STATUS_PATH = Path(os.environ.get("HOME", "/home/appuser")) / ".relay" / "worker_status.json"
# Heartbeat is considered stale after this many seconds (heartbeat_interval
# default is 8s; we allow generous headroom for a slow relay or a loaded box).
STALE_AFTER_SECONDS = 90


def main() -> int:
    if not STATUS_PATH.exists():
        print(f"healthcheck: status file missing ({STATUS_PATH})", file=sys.stderr)
        return 1
    try:
        data = json.loads(STATUS_PATH.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"healthcheck: cannot read status file: {exc}", file=sys.stderr)
        return 1

    # A daemon that flagged an auth-loop is unhealthy — the token is bad
    # and no work will be claimed until an operator intervenes.
    if data.get("auth_loop"):
        print("healthcheck: auth_loop flagged — token invalid", file=sys.stderr)
        return 1

    last_hb = data.get("last_heartbeat")
    if not last_hb:
        print("healthcheck: no last_heartbeat in status file", file=sys.stderr)
        return 1
    try:
        hb = datetime.fromisoformat(last_hb)
        if hb.tzinfo is None:
            hb = hb.replace(tzinfo=timezone.utc)
    except ValueError:
        print(f"healthcheck: malformed last_heartbeat {last_hb!r}", file=sys.stderr)
        return 1

    age = (datetime.now(timezone.utc) - hb).total_seconds()
    if age > STALE_AFTER_SECONDS:
        print(f"healthcheck: heartbeat stale ({age:.0f}s > {STALE_AFTER_SECONDS}s)", file=sys.stderr)
        return 1

    pid = data.get("pid")
    if not pid:
        print("healthcheck: no pid in status file", file=sys.stderr)
        return 1

    # pid present + heartbeat fresh = healthy. We deliberately do not
    # signal-check the pid (a zombie would also have a stale heartbeat).
    return 0


if __name__ == "__main__":
    sys.exit(main())