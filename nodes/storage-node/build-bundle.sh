#!/usr/bin/env bash
set -euo pipefail

# Build a local deploy bundle for the AI Relay Storage Node.
# The bundle contains only the files needed to build the Docker image.
# Copy the resulting .tar.gz to the NAS and extract it there, then run:
#   docker compose up -d --build

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../" && pwd)"
OUTPUT_DIR="${1:-$REPO_ROOT/dist}"
BUNDLE_DIR="$OUTPUT_DIR/storage-node-bundle"
TARBALL="$OUTPUT_DIR/storage-node-bundle.tar.gz"

mkdir -p "$BUNDLE_DIR"
rm -rf "$BUNDLE_DIR"/*

cp "$SCRIPT_DIR/Dockerfile" "$BUNDLE_DIR/"
cp "$SCRIPT_DIR/requirements.txt" "$BUNDLE_DIR/"
cp "$SCRIPT_DIR/storage_node.py" "$BUNDLE_DIR/"
cp "$SCRIPT_DIR/docker-compose.yml" "$BUNDLE_DIR/"
cp "$SCRIPT_DIR/README.md" "$BUNDLE_DIR/"
cp "$REPO_ROOT/nodes/common/poller.py" "$BUNDLE_DIR/"
cp "$REPO_ROOT/nodes/common/relay_config.json.example" "$BUNDLE_DIR/"

cd "$OUTPUT_DIR"
tar -czf "$TARBALL" -C "$BUNDLE_DIR" .

echo "Bundle created: $TARBALL"
echo ""
echo "Deploy on the NAS:"
echo "  scp $TARBALL user@nas:/tmp/"
echo "  ssh user@nas mkdir -p /volume1/ai-relay-storage && tar -xzf /tmp/storage-node-bundle.tar.gz -C /volume1/ai-relay-storage"
echo "  ssh user@nas 'cd /volume1/ai-relay-storage && docker compose up -d --build && docker compose run --rm ai-relay-storage python /app/storage_node.py --register'"
