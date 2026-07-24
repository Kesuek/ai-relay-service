#!/usr/bin/env bash
# ssn-capability-pages.sh — Handler for the `ssn.capability-pages` capability.
#
# Runs on the Server-Side Node (SSN). Manages HTML dashboard pages for other
# capabilities under ~/.ssn/pages/<capability>.html.
#
# Contract (see nodes/common/handler_runner.py):
#   stdin:  stage payload as JSON, e.g.:
#             {"action": "add", "capability": "image.generate.mflux",
#              "artifact_id": "artifact_xxx"}
#   env:    RELAY_BASE_URL, RELAY_TOKEN_FILE, RELAY_NODE_ID, ...
#   stdout: valid JSON result dict (exit 0) or stderr+non-zero on error.
#
# Actions:
#   add     — download <artifact_id> and store it as <capability>.html
#   update  — same as add (overwrite)
#   delete  — remove <capability>.html
#   list    — print JSON array of capability names with a page present
#
# The add/update path invokes the node-cli download command. The exact
# invocation is overridable via the NODE_CLI_DOWNLOAD env var so tests can
# substitute a mock; the default is the real ``python -m nodes.common.node_cli
# artifact download``.
set -euo pipefail

PAGES_DIR="${HOME}/.ssn/pages"
mkdir -p "$PAGES_DIR"

payload="$(cat)"

# Parse the payload with python (always available — the SSN runs node-cli).
read -r action capability artifact_id <<EOF
$(python3 -c '
import json, sys
p = json.load(sys.stdin)
print(p.get("action") or "", p.get("capability") or "", p.get("artifact_id") or "")
' <<<"$payload")
EOF

case "$action" in
  add|update)
    if [ -z "$capability" ] || [ -z "$artifact_id" ]; then
      echo 'add/update requires "capability" and "artifact_id"' >&2
      exit 2
    fi
    # Reject path separators / traversal in the capability name.
    case "$capability" in
      *"/"*|*"\\") echo "capability must not contain path separators" >&2; exit 2 ;;
      .*|".") echo "capability must not be a path-traversal segment" >&2; exit 2 ;;
    esac
    target="${PAGES_DIR}/${capability}.html"
    # Download via the SSN's authenticated relay session. NODE_CLI_DOWNLOAD
    # is used by the test-suite to substitute a mock downloader; the default
    # invokes the real node-cli shipped with this repo.
    if [ -z "${NODE_CLI_DOWNLOAD:-}" ]; then
      NODE_CLI_DOWNLOAD="python3 -m nodes.common.node_cli artifact download"
    fi
    # shellcheck disable=SC2086
    $NODE_CLI_DOWNLOAD "$artifact_id" --output "$target" >/dev/null
    size="$(stat -c '%s' "$target" 2>/dev/null || stat -f '%z' "$target" 2>/dev/null || echo 0)"
    printf '{"status":"ok","action":"%s","capability":"%s","path":"%s","size_bytes":%s}\n' \
      "$action" "$capability" "$target" "$size"
    ;;

  delete)
    if [ -z "$capability" ]; then
      echo 'delete requires "capability"' >&2
      exit 2
    fi
    case "$capability" in
      *"/"*|*"\\") echo "capability must not contain path separators" >&2; exit 2 ;;
      .*|".") echo "capability must not be a path-traversal segment" >&2; exit 2 ;;
    esac
    target="${PAGES_DIR}/${capability}.html"
    if [ -f "$target" ]; then
      rm -f "$target"
      printf '{"status":"ok","action":"delete","capability":"%s","deleted":true}\n' "$capability"
    else
      printf '{"status":"ok","action":"delete","capability":"%s","deleted":false}\n' "$capability"
    fi
    ;;

  list)
    caps=()
    shopt -s nullglob
    for f in "$PAGES_DIR"/*.html; do
      name="$(basename "$f" .html)"
      caps+=("\"$name\"")
    done
    if [ "${#caps[@]}" -eq 0 ]; then
      printf '{"status":"ok","action":"list","capabilities":[]}\n'
    else
      joined="$(IFS=,; printf '%s' "${caps[*]}")"
      printf '{"status":"ok","action":"list","capabilities":[%s]}\n' "$joined"
    fi
    ;;

  *)
    echo "unknown action: ${action:-<empty>}" >&2
    exit 2
    ;;
esac