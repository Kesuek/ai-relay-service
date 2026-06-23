# AI Relay Agent Integration

This directory contains a reference KI-capable worker that registers as a node
in the AI Relay cluster and delegates every claimed stage to the local Hermes
AI.

## Files

| File | Purpose |
|---|---|
| `ai-relay-agent-poller.py` | KI-capable delegator worker. Uses `nodes/common/poller.py` for auth, heartbeat, claim, and completion. Hands stage payloads to the local `hermes` CLI. |
| `ai-relay-agent-poller.service` | systemd user unit for running the worker permanently. |

## How it works

1. The poller loads `~/.relay/ai-relay-agent.json` and `~/.relay/relay_config.json`.
2. It ensures a valid runtime token is available, refreshing or recovering via
   `/relay/v2/auth/refresh` as needed.
3. It heartbeats every 8 seconds with capability `agent.task`.
4. When it claims a stage, it builds a prompt from the stage payload and runs:

   ```bash
   hermes -z "<prompt>" -t terminal,file,web,image_gen
   ```

5. It completes the stage with the stdout/stderr/returncode from Hermes.

This keeps tool selection, prompt interpretation, and environment handling inside
the local Hermes session, not in the worker code.

## Setup

1. Install Hermes CLI and make sure `hermes` is on the worker PATH.
2. Register the node with the relay:

   ```bash
   curl -X POST "http://${RELAY_HOST}:8788/relay/v2/auth/register" \
     -H "Content-Type: application/json" \
     -d '{
       "node_name": "ai-relay-agent",
       "capabilities": [{"name": "agent.task", "version": "1.0.0"}]
     }'
   ```

3. Save `node_id` and `registration_secret` to `~/.relay/ai-relay-agent.json`.
4. Create `~/.relay/relay_config.json` from `nodes/common/relay_config.json.example`.
5. Approve the node in the relay dashboard.
6. Install and start the systemd unit:

   ```bash
   systemctl --user daemon-reload
   systemctl --user enable --now /home/felix/projects/ai-relay-service/examples/agent-integration/ai-relay-agent-poller.service
   ```

## Submitting work

From any client or node:

```bash
curl -X POST "http://${RELAY_HOST}:8788/relay/v2/scheduler/tasks" \
  -H "Authorization: Bearer <rt_...>" \
  -H "Content-Type: application/json" \
  -d '{
    "task_name": "ask-local-agent",
    "stages": [
      {
        "stage_name": "execute",
        "capability": "agent.task",
        "payload": {"prompt": "generate an image of a small robot"}
      }
    ],
    "priority": 1
  }'
```

The relay routes the stage to the agent node. The agent delegates the prompt to
Hermes, which decides to run the appropriate tool.
