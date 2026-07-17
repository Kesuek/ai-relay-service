# node-cli — Command Reference

`node-cli` is the generic, capability-driven daemon & CLI for the AI-Relay-Service.
It is fully **capability-agnostic**: all behaviour is driven by an external
YAML profile (see [capabilities.md](capabilities.md)). The CLI manages a
background daemon, performs one-shot operations against the relay, and manages
capability profiles.

## Invocation

```bash
python -m nodes.common.node_cli <command> [options]
# or, when installed as an entrypoint:
node-cli <command> [options]
```

The CLI requires a registered node — `~/.relay/ai-relay-agent.json` and
`~/.relay/ai-relay-agent.token` must exist (see
[setup.md](setup.md) for registration).

## Global options

| Option | Default | Description |
|---|---|---|
| `--log-level <LEVEL>` | `RELAY_LOG_LEVEL` env or `INFO` | Log level: `DEBUG`, `INFO`, `WARNING`, `ERROR`. |

The global `--log-level` option is accepted by every subcommand that performs
relay I/O (daemon actions, heartbeat, claim, complete, task, artifact,
capabilities validate/publish/diff). Pure-local subcommands
(`capabilities list`/`current`, `status`, `reload`) use `RELAY_LOG_LEVEL` /
`INFO`.

## Commands

| Command | Purpose |
|---|---|
| [`daemon`](#daemon) | Control the background daemon |
| [`heartbeat`](#heartbeat) | Send a single heartbeat and exit |
| [`claim`](#claim) | Claim one stage for a capability |
| [`complete`](#complete) | Complete a claimed stage |
| [`task submit`](#task-submit) | Submit a single-stage task |
| [`capabilities`](#capabilities) | Capability profile management |
| [`status`](#status) | Print `worker_status.json` |
| [`reload`](#reload) | Send SIGHUP to running daemon |
| [`artifact`](#artifact) | Artifact upload / download |

---

## daemon

Control the background daemon. The daemon writes a PID file at
`~/.relay/node-cli.pid` and a log file at `~/.relay/node-cli.log`.

### Syntax

```
node-cli daemon <action>
```

### Actions

| Action | Behaviour |
|---|---|
| `start` | Start the background daemon (self-spawns `python -m nodes.common.node_cli --daemon-internal`, writes PID file). No-op if already running. |
| `stop` | Send `SIGTERM` to the daemon (falls back to `SIGKILL` after 10s), then remove the PID file. |
| `restart` | `stop` then `start`. |
| `foreground` | Run the daemon in the foreground (for testing / systemd). Writes a PID file so `status`/`stop` still work. |
| `status` | Print daemon status (pid, running, active profile, last heartbeat, heartbeat status, tasks completed/failed, in-flight stages). Exit `0` when running, `1` when not running. |

### Examples

```bash
# Start in the background
node-cli daemon start
# -> daemon started (pid 12345); log: /home/user/.relay/node-cli.log

# Check status
node-cli daemon status
# -> pid: 12345
# -> running: True
# -> active_profile: default
# -> last_heartbeat: 2026-07-17T10:23:11+00:00
# -> heartbeat_status: ok
# -> tasks_completed: 5
# -> tasks_failed: 0

# Stop
node-cli daemon stop
# -> daemon stopped

# Run in the foreground (systemd / testing)
node-cli daemon foreground
```

### Exit codes

| Code | Condition |
|---|---|
| 0 | Action completed (including `start` when already running) |
| 1 | Inner process exited early, or daemon did not stop, or `status` reports not running |

---

## heartbeat

Send a single heartbeat to the relay using the active capability profile and
exit. Useful for testing connectivity and credentials.

### Syntax

```
node-cli heartbeat
```

### Example

```bash
node-cli heartbeat
# -> {
#   "node_id": "V34ETT74",
#   "status": "ok",
#   ...
# }
```

### Exit codes

| Code | Condition |
|---|---|
| 0 | Heartbeat accepted by the relay |
| 1 | HTTP / network error (no token, recovery failed, relay returned error) |

---

## claim

Claim one pending stage for a capability. The capability must be advertised by
the active capability profile.

### Syntax

```
node-cli claim <capability>
```

### Arguments

| Argument | Required | Description |
|---|---|---|
| `capability` | yes | Capability name to claim (matched exactly by the scheduler) |

### Example

```bash
node-cli claim chat.ai
# -> {"claimed": true, "stage": {"stage_id": "stg_...", ...}}
# or
# -> {"claimed": false}
```

### Exit codes

| Code | Condition |
|---|---|
| 0 | Claim request completed (regardless of whether a stage was claimed) |
| 1 | HTTP / network error |

---

## complete

Complete a previously claimed stage by submitting a result dict from a JSON
file.

### Syntax

```
node-cli complete <stage_id> --task <task_id> --result-file <path>
```

### Arguments

| Argument | Required | Default | Description |
|---|---|---|---|
| `stage_id` | yes | — | Stage ID to complete |
| `--task` | yes | — | Task ID the stage belongs to |
| `--result-file` | yes | — | Path to a JSON file containing the result dict |

### Example

```bash
echo '{"answer": "It is 21:45 in Tokyo."}' > /tmp/result.json
node-cli complete stg_abc123 --task tsk_def456 --result-file /tmp/result.json
# -> {"ok": true, ...}
```

On failure put the error inside the result dict:

```bash
echo '{"error": "model unavailable"}' > /tmp/result.json
node-cli complete stg_abc123 --task tsk_def456 --result-file /tmp/result.json
```

### Exit codes

| Code | Condition |
|---|---|
| 0 | Stage completed |
| 1 | HTTP / network error |
| 2 | Result file not found or not valid JSON |

---

## task submit

Submit a single-stage task to the relay. The stage is given inline as
`<capability>:<json-payload>`.

### Syntax

```
node-cli task submit --stage <capability>:<json-payload> [--name <name>] [--priority <0-10>]
```

### Arguments

| Argument | Required | Default | Description |
|---|---|---|---|
| `--stage` | yes | — | Stage as `<capability>:<json-payload>` (payload must be a JSON object) |
| `--name` | no | `""` | Task name |
| `--priority` | no | `0` | Task priority, integer 0–10 (higher = more important) |

### Examples

```bash
node-cli task submit \
  --stage 'chat.ai:{"question":"What is the time in Tokyo?"}' \
  --name "tokyo-time" \
  --priority 3
```

Submit with an empty payload:

```bash
node-cli task submit --stage 'storage.archive:{}'
```

### Exit codes

| Code | Condition |
|---|---|
| 0 | Task submitted |
| 1 | HTTP / network error, or invalid `--stage` syntax |
| 2 | (reserved) |

---

## capabilities

Capability profile management. Profiles are YAML files in
`~/.relay/capabilities.d/`; the active profile is
`~/.relay/capabilities.active.yaml`. See [capabilities.md](capabilities.md)
for the profile format and validation rules.

### Syntax

```
node-cli capabilities <action> [profile]
```

### Actions

#### `list`

List profiles in `~/.relay/capabilities.d/`. The active profile is marked
with `*`.

```bash
node-cli capabilities list
# -> * default
# ->   staging
```

#### `validate [profile]`

Validate a profile. With no argument, validates the active profile. Prints the
parsed capabilities on success.

```bash
node-cli capabilities validate default
# -> OK default (2 capabilities)
# ->   - chat.ai v1.0.0 auto_publish=True claimable=True max_parallel=2 timeout=300
```

#### `publish <profile>`

Validate the working profile, then atomically copy it to
`~/.relay/capabilities.active.yaml` and record the profile name. If the daemon
is running, send `SIGHUP` so it reloads immediately.

```bash
node-cli capabilities publish default
# -> published 'default' -> capabilities.active.yaml (sent SIGHUP to pid 12345)
```

#### `diff [profile]`

Diff the working profile against the active profile. With no argument, diffs
the active profile against itself (always "no differences").

```bash
node-cli capabilities diff staging
# -> diff active -> staging:
# -> + image.flux v1.2.0
# -> - chat.ai
# -> ~ storage.archive:
# ->     version: 1.0.0 -> 1.1.0
```

#### `current`

Print the name of the active profile. Exit `1` if no active profile is set.

```bash
node-cli capabilities current
# -> default
```

### Exit codes

| Code | Condition |
|---|---|
| 0 | Action succeeded |
| 1 | Validation error, profile not found, no active profile, or invalid active profile |

---

## status

Print the contents of `~/.relay/worker_status.json` (written by the daemon
after every heartbeat). Includes PID, node_id, started_at, last_heartbeat,
heartbeat_status, active_profile, capabilities, in-flight stages, and
tasks_completed/failed counters.

### Syntax

```
node-cli status
```

### Exit codes

| Code | Condition |
|---|---|
| 0 | Status file printed |
| 1 | No status file (daemon not started yet) or status file is not valid JSON |

---

## reload

Send `SIGHUP` to the running daemon so it invalidates the capability cache and
reloads the active profile at the next heartbeat.

### Syntax

```
node-cli reload
```

### Exit codes

| Code | Condition |
|---|---|
| 0 | SIGHUP sent |
| 1 | Daemon not running or signal failed |

---

## artifact

Artifact upload and download. Artifacts are files stored on the relay under
`~/.relay/artifacts/` with metadata in the database.

### `artifact upload`

Upload a local file as an artifact to the relay.

#### Syntax

```
node-cli artifact upload <file> [--name <name>] [--task-id <id>] [--stage-id <id>]
```

#### Arguments

| Argument | Required | Default | Description |
|---|---|---|---|
| `file` | yes | — | Path to the file to upload |
| `--name` | no | filename | Artifact name |
| `--task-id` | no | — | Optional task ID to associate with |
| `--stage-id` | no | — | Optional stage ID to associate with |

#### Example

```bash
node-cli artifact upload /tmp/image.png --task-id tsk_abc --stage-id stg_answer
# -> {"artifact_id": "artifact_...", "name": "image.png", "size_bytes": 123456}
```

#### Exit codes

| Code | Condition |
|---|---|
| 0 | Upload succeeded |
| 1 | HTTP / network error |
| 2 | File not found |

### `artifact download`

Download an artifact by ID from the relay. Streams to disk in 64 KiB chunks.
The output filename is derived from the `Content-Disposition` header when no
`--output` is given.

#### Syntax

```
node-cli artifact download <artifact_id> [--output <path>]
```

#### Arguments

| Argument | Required | Default | Description |
|---|---|---|---|
| `artifact_id` | yes | — | The artifact ID to download |
| `--output`, `-o` | no | server-provided name | Output path |

#### Example

```bash
node-cli artifact download artifact_a1B2c3D4 -o /tmp/out.png
# -> Downloaded 123456 bytes to /tmp/out.png
```

#### Exit codes

| Code | Condition |
|---|---|
| 0 | Download succeeded |
| 1 | HTTP / network error, or auth refresh failed |

---

## Configuration

### File paths

All paths are relative to `~/.relay/` unless noted.

| Path | Description |
|---|---|
| `ai-relay-agent.json` | Node metadata (node_id, node_name, capabilities, registration_secret, base_url) |
| `ai-relay-agent.token` | Runtime token (`rt_…`) |
| `relay_config.json` | Poller / daemon config (see below) |
| `worker_status.json` | Daemon status file (written after every heartbeat) |
| `capabilities.active.yaml` | Active capability profile |
| `capabilities.active.profile` | Name of the active profile |
| `capabilities.d/` | Working capability profiles |
| `node-cli.pid` | Daemon PID file |
| `node-cli.log` | Daemon log file |

### `relay_config.json` defaults

```json
{
  "base_url": null,
  "heartbeat_interval": 8,
  "claim_interval": 5,
  "status_interval": 7200,
  "rt_refresh_before_seconds": 86400,
  "rs_refresh_before_seconds": 3600,
  "request_timeout": 10,
  "task_timeout": 600,
  "load_cap": 1.0,
  "log_level": "INFO",
  "background_heartbeat": true
}
```

### Environment variables

| Variable | Used by | Description |
|---|---|---|
| `RELAY_BASE_URL` | all commands | Override `base_url` from `relay_config.json` |
| `RELAY_HEARTBEAT_INTERVAL` | daemon | Override `heartbeat_interval` (integer seconds) |
| `RELAY_CLAIM_INTERVAL` | daemon | Override `claim_interval` (integer seconds) |
| `RELAY_LOG_LEVEL` | all commands | Default log level when `--log-level` is not passed |
| `RELAY_PROFILES_DIR` | capabilities | Override the `capabilities.d/` directory |

> **Token is read from a file, not an env var.** The CLI loads the runtime
> token from `~/.relay/ai-relay-agent.token` only. A `RELAY_RUNTIME_TOKEN`
> env-var fallback is shown by the dashboard UI but is **not yet honoured**
> by the CLI — keep the token in the file (with `chmod 600`; see
> [setup.md §Token storage & permissions](setup.md)).
>
> **Server-only variables, not used by nodes.** The relay server reads a
> number of `RELAY_*` variables that the node CLI ignores. Listing them
> here so you do not set them on a node by mistake:
> `RELAY_SESSION_SECRET` (dashboard cookie signing),
> `RELAY_ENABLE_MDNS` / `RELAY_MDNS_HOSTNAME` (relay mDNS advertisement),
> `RELAY_ENABLE_MASTER_SEED_LOGIN` (recovery mode),
> `RELAY_DB_PATH`, `RELAY_ARTIFACTS_DIR`, `RELAY_MAX_UPLOAD_BYTES`,
> `RELAY_TOKEN_TTL_HOURS`, `RELAY_SESSION_COOKIE_SECURE`, etc. These belong
> in the relay's `~/.relay/config.yaml` or its systemd unit, not the node's.
> The full server config is documented in
> [../server/setup.md §11 Configuration reference](../server/setup.md).

### Handler environment variables

When the daemon runs an external handler for a claimable capability, it sets
these environment variables (see [capabilities.md](capabilities.md) for the
handler contract):

| Variable | Description |
|---|---|
| `RELAY_STAGE_ID` | Stage ID from the claim |
| `RELAY_TASK_ID` | Task ID from the claim |
| `RELAY_CAPABILITY` | Capability name |
| `RELAY_NODE_ID` | Assigned node ID |
| `RELAY_BASE_URL` | Relay server URL |
| `RELAY_TOKEN_FILE` | Path to the runtime token file |

Per-capability overrides are also honoured:
`RELAY_CAPABILITY_<NAME>_HANDLER` and `RELAY_CAPABILITY_<NAME>_MAX_PARALLEL`
(where `<NAME>` is the capability name with non-alphanumeric chars replaced by
underscores, uppercased).

---

## Error handling

- **Token refresh:** every relay request retries exactly once after a token
  refresh on `401`/`403`. If refresh fails, the client attempts recovery with
  the `registration_secret`; if that also fails the command exits `1`.
- **Missing token:** if `~/.relay/ai-relay-agent.token` is absent, the CLI
  attempts registration-secret recovery immediately on startup.
- **Network errors** (`httpx.HTTPError`) are reported on stderr and exit `1`.
- **`KeyboardInterrupt`** exits `130`.
- **Invalid CLI arguments** exit `2` (argparse default).