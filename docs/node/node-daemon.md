# node-daemon — SSE-driven Node Worker

`node-daemon` is an alternative to `node-cli daemon` that uses **Server-Sent Events (SSE)** instead of polling. It subscribes to the relay's event stream and reacts to `task_created` and `stage_claimed` events in real time, rather than polling the claim endpoint every 5 seconds.

## Quick Start

```bash
# Install (one-time)
pip install -e .

# Run in foreground (for testing)
node-daemon --foreground

# Run as systemd service
systemctl --user enable --now ai-relay-node-daemon.service
```

## CLI Options

| Option | Default | Description |
|---|---|---|
| `--foreground` | — | Run in foreground (no PID file, logs to stderr) |
| `--log-level LOG_LEVEL` | `INFO` | Log level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |

## How It Works

```
┌─────────────┐     SSE stream      ┌──────────────┐
│   Relay     │ ──────────────────→ │ node-daemon  │
│  (Server)   │   task_created,     │              │
│             │   stage_claimed     │  ┌─────────┐  │
│             │                     │  │ SSE     │  │
│             │                     │  │ Client  │  │
│             │                     │  └────┬────┘  │
│             │                     │       │       │
│             │                     │  ┌────▼────┐  │
│             │                     │  │ Worker  │  │
│             │                     │  │ (claim) │  │
│             │                     │  └────┬────┘  │
│             │ ←──── claim/ ──────│         │       │
│             │      execute/      │  ┌────▼────┐  │
│             │      complete      │  │ Handler │  │
│             │                     │  └─────────┘  │
└─────────────┘                     └──────────────┘
```

Three threads run inside the daemon:

1. **Heartbeat** — sends a heartbeat every 30s (same as `node-cli daemon`)
2. **SSE Client** — maintains a persistent HTTP connection to the relay's event stream
3. **Worker** — triggered by events, iterates claimable capabilities and claims/executes stages

## Comparison: `node-cli daemon` vs `node-daemon`

| Aspect | `node-cli daemon` | `node-daemon` |
|---|---|---|
| Mechanism | Polling (every 5s) | SSE (event-driven) |
| Latency | ~5s | Real-time |
| Requests | ~720/h (claim) | ~1/h (SSE connection) |
| Complexity | Simple | Moderate (reconnect, async) |
| When to use | Stable environments | Real-time needed |

## Subscribed Events

The daemon subscribes to `stage_claimed` and `task_created` events. When either arrives, it triggers a claim sweep: for each claimable capability in the active profile, it calls `claim()`. If a stage is returned, it runs the handler and completes the stage.

## Reconnection

If the SSE connection drops (server restart, network issue), the daemon waits 5 seconds and reconnects automatically. The heartbeat thread keeps the node alive during reconnection.

## systemd Service

The service file is at `systemd/ai-relay-node-daemon.service`. It expects:

- `RELAY_BASE_URL` — the relay server URL (default: `http://127.0.0.1:8788`)
- `RELAY_LOG_LEVEL` — log level (default: `INFO`)

Install it:

```bash
cp systemd/ai-relay-node-daemon.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now ai-relay-node-daemon.service
```

## Logs

```bash
journalctl --user -u ai-relay-node-daemon.service -f
```

## Switching from `node-cli daemon`

```bash
# Stop the polling daemon
systemctl --user stop ai-relay-node-cli.service
systemctl --user disable ai-relay-node-cli.service

# Start the SSE daemon
systemctl --user enable --now ai-relay-node-daemon.service
```

Both daemons use the same config, token, and capabilities. Only the claim mechanism differs.
