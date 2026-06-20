# Example Relay Nodes

This directory contains standalone example nodes for the AI-Relay-Service v2.
They run as external processes and talk to the core over the public HTTP/SSE
API. They do **not** import any `relay_server` internals.

## Files

- `node_base.py` — reusable `BaseNode` / `run_node()` implementation shared by the example nodes
- `relay_client.py` — minimal shared HTTP client (register, heartbeat, claim, complete, SSE, approve)
- `vault_node.py` — thin shell advertising the `vault` capability
- `board_node.py` — thin shell advertising the `board` capability
- `approve_nodes.py` — helper that approves pending nodes and writes runtime tokens

## How it works

1. Start the relay server.
2. Initialize the master admin seed once.
3. Start the example nodes. Each node registers as **pending** and waits.
4. Run `approve_nodes.py` with the master seed to approve the nodes.
   It writes each node's runtime token to `~/.relay/<node_id>.token`.
5. The nodes detect the runtime token, start heartbeating, and begin
   claiming/completing stages that match their capability.

## Quick manual test

Terminal 1 — start the server:

```bash
cd ~/projects/ai-relay-service
source .venv/bin/activate
python -m relay_server.main server --port 8788
```

Terminal 2 — create the master seed and save it:

```bash
cd ~/projects/ai-relay-service
source .venv/bin/activate
python -m relay_server.main admin init-master
# Copy the SECRET value, e.g. adm_xxxxxxxxxxxx
```

Terminal 3 — start the example nodes:

```bash
cd ~/projects/ai-relay-service/examples/nodes
source ../../.venv/bin/activate
python vault_node.py --node-id VT999999 --base-url http://127.0.0.1:8788 &
python board_node.py --node-id BRD77778 --base-url http://127.0.0.1:8788 &
```

Terminal 4 — approve the nodes:

```bash
cd ~/projects/ai-relay-service/examples/nodes
source ../../.venv/bin/activate
RELAY_MASTER_SECRET="adm_xxxxxxxxxxxx" \
  python approve_nodes.py \
  --base-url http://127.0.0.1:8788 \
  --capabilities vault,board
```

Terminal 5 — submit a task that exercises both capabilities.
First register an admin node with the master secret to obtain an admin token,
then POST to `/relay/v2/scheduler/tasks`:

```json
{
  "task_name": "Demo vault+board pipeline",
  "stages": [
    {"stage_name": "store_secret", "capability": "vault", "payload": {"secret_count": 3}},
    {"stage_name": "publish_summary", "capability": "board", "payload": {"posts": 1}}
  ]
}
```

Watch the node terminals: they should claim and complete their respective
stages. You can also query the task status with the admin token:

```bash
httpx get http://127.0.0.1:8788/relay/v2/scheduler/tasks \
  Authorization:"Bearer <admin-token>"
```

## Configuration

All nodes accept the following environment variables / CLI flags:

| Variable | Flag | Default | Description |
|----------|------|---------|-------------|
| `RELAY_BASE_URL` | `--base-url` | `http://127.0.0.1:8788` | Relay server URL |
| `RELAY_NODE_ID` | `--node-id` | `VT999999` / `BRD77778` | Unique 8-char node ID |
| `RELAY_NODE_NAME` | `--node-name` | `Vault Node` / `Board Node` | Human-readable name |
| `RELAY_ENDPOINT` | `--endpoint` | none | Optional endpoint advertised for this node |
| `RELAY_RUNTIME_TOKEN` | `--runtime-token` | none | Skip registration, use existing runtime token |
| `RELAY_TOKEN_FILE` | `--token-file` | `~/.relay/<node_id>.token` | File to watch for runtime token |
| `RELAY_HEARTBEAT_INTERVAL` | `--heartbeat-interval` | `10` | Seconds between heartbeats |
| `RELAY_CLAIM_INTERVAL` | `--claim-interval` | `2` | Seconds between claim attempts |
| `RELAY_LOG_LEVEL` | `--log-level` | `INFO` | Logging level |

`approve_nodes.py` additionally accepts:

| Variable | Flag | Default | Description |
|----------|------|---------|-------------|
| `RELAY_MASTER_SECRET` | `--master-secret` | required | Master admin seed |
| `RELAY_APPROVE_CAPABILITIES` | `--capabilities` | `vault,board` | Capabilities to approve |
| `RELAY_TOKEN_DIR` | `--token-dir` | `~/.relay` | Where runtime token files are written |

## Notes

- The core invalidates the temporary token when an admin approves a node, so the
  node cannot auto-upgrade its own token. The runtime token must be supplied by
  an external actor (this demo uses `approve_nodes.py` writing a token file).
- Example nodes use only the public v2 API and can run on a different host than
  the relay core as long as they can reach `RELAY_BASE_URL`.
