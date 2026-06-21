#!/usr/bin/env bash
set -euo pipefail

# Deploy the AI Relay Storage Node on a NAS (or any Docker host).
# Run this script on the target machine via SSH.

RELAY_BASE_URL="${RELAY_BASE_URL:-http://ai-relay.local:8788}"
RELAY_NODE_NAME="${RELAY_NODE_NAME:-nas-storage-01}"
RELAY_STORAGE_PATH="${RELAY_STORAGE_PATH:-/volume1/ai-relay-storage}"
COMPOSE_URL="https://raw.githubusercontent.com/Kesuek/ai-relay-service/main/nodes/storage-node/docker-compose.yml"

mkdir -p "$RELAY_STORAGE_PATH"
cd "$RELAY_STORAGE_PATH"

if ! command -v docker &> /dev/null; then
    echo "ERROR: Docker is not installed on this machine." >&2
    exit 1
fi

if ! docker compose version &> /dev/null && ! docker-compose version &> /dev/null; then
    echo "ERROR: Docker Compose is not installed." >&2
    exit 1
fi

echo "Downloading compose file..."
curl -fsSL "$COMPOSE_URL" -o docker-compose.yml

echo "Starting storage node container..."
RELAY_BASE_URL="$RELAY_BASE_URL" \
RELAY_NODE_NAME="$RELAY_NODE_NAME" \
RELAY_STORAGE_PATH="$RELAY_STORAGE_PATH" \
docker compose up -d --build

echo "Registering node with relay..."
sleep 2
docker compose run --rm ai-relay-storage python /app/register.py || true

echo ""
echo "Storage node deployed. Next steps:"
echo "1. Find the node_id in $RELAY_STORAGE_PATH/.relay/ai-relay-agent.json"
echo "2. Approve the node via the relay dashboard or:"
echo "   curl -H \"Authorization: Bearer <MASTER_SECRET>\" \\"
echo "     -X POST $RELAY_BASE_URL/relay/v2/admin/nodes/<NODE_ID>/approve \\"
echo "     -d '{\"role\":\"service\",\"capabilities\":[{\"name\":\"storage.archive\",\"version\":\"1.0.0\"}]}'"
