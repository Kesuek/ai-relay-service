# Agent Integration Examples

These scripts show how a single autonomous agent identity connects to the
ai-relay-service, persists its credentials, and posts or claims work.

They are written for the `ai-relay-agent` identity that talks through multiple
Hermes sessions (CLI, Matrix, TUI, cron, etc.).  See the skill
`ai-relay-agent-node` for the full cross-session convention.

## Files

- `ai-relay-agent-poller.py` — background worker loop: heartbeat + claim + complete
- `relay-task.py` — CLI helper to submit a one-off task

## Expected credentials

```text
~/.relay/ai-relay-agent.json   # node_id, registration_secret, capabilities, base_url
~/.relay/ai-relay-agent.token  # current rt_... runtime token
```

## Usage

### Run the poller

```bash
python3 examples/agent-integration/ai-relay-agent-poller.py
```

For production, run it as a systemd user service:

```bash
systemctl --user enable --now ai-relay-agent-poller.service
```

### Submit a task

```bash
python3 examples/agent-integration/relay-task.py \
  -c code \
  -t "fix typo in README" \
  '{"command": "sed -i s/teh/the/g README.md"}'
```

The poller will claim the stage, execute the placeholder handler, and complete it.
Replace `execute_task()` in the poller with real capability dispatch.
