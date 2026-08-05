#!/usr/bin/env bash
# AI-Relay-Service server container entrypoint.
#
# Responsibilities:
#   1. Ensure the master admin seed exists (deterministic via RELAY_MASTER_SEED,
#      otherwise generated on first run). The DB itself is migrated by the
#      server's FastAPI lifespan on startup.
#   2. exec the server process (replacing the shell so signals reach it).

set -euo pipefail

# relay-server admin init-master returns 0 if a new seed was created, 1 if one
# already exists. Both are fine here: we must keep running either way. Any
# other failure (DB unreachable, etc.) aborts the container (fail-fast) so the
# orchestrator can restart it.
set +e
relay-server admin init-master
seed_rc=$?
set -e

if [ "$seed_rc" -eq 0 ]; then
    echo "[entrypoint] master seed created."
elif [ "$seed_rc" -eq 1 ]; then
    echo "[entrypoint] master seed already exists — continuing."
else
    echo "[entrypoint] ERROR: could not initialize master seed (rc=$seed_rc)." >&2
    exit 1
fi

# exec so uvicorn becomes a direct child and receives SIGTERM/SIGINT.
exec "$@"
