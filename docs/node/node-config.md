# Node Configuration (`node.yaml`)

The `~/.relay/node.yaml` file is the **central configuration file for a
worker node**. It replaces the old `capabilities.active.yaml` and can hold
both node-level settings and capability definitions in a single YAML file.

```yaml
# ~/.relay/node.yaml
node_name: felix-cyberfox
description: "Local AI worker on the Proxmox host"
status: busy

capabilities:
  - name: chat.ai
    version: "1.0.0"
    handler: /opt/relay/handlers/chat-ai.sh
    claimable: true
    max_parallel: 2
    timeout: 300
```

## Node-level fields

These fields live at the top level of `node.yaml` and configure the node
itself rather than individual capabilities.

### `node_name` (optional)

Human-friendly name for this node. When set, the name is forwarded to the
server in every heartbeat and shown in the dashboard and `node-cli node list`.

### `description` (optional)

Free-text description of the node. Forwarded to the server in every heartbeat.
Useful for annotating what hardware or software the node runs.

### `status` (optional)

Operator-requested node status. Can be one of:

| Value | Meaning |
|-------|---------|
| *(not set)* | Normal operation — the node claims and executes stages |
| `busy` | The node signals that it cannot accept new work. The scheduler will not assign stages to it. Existing stages continue running. |
| `idle` | Available but explicitly marking that there is nothing to do. Behaves like `online`. |
| `online` | Default. Overrides any previous `busy`/`idle` request. |

> **Note:** `busy` and `idle` are set automatically by `node-cli node busy`
> and `node-cli node idle`. Writing them directly into `node.yaml` works but
> is not the intended workflow — use the CLI instead (see below).

## Capability profiles

Capability definitions live under the `capabilities` key as a list. This
field is **optional** — a node can register without any capabilities and
add them later at runtime.

For a full reference of capability fields see [`capabilities.md`](capabilities.md).

### Working profiles

For day-to-day editing, keep your capabilities in separate YAML files under
`~/.relay/profiles.d/`:

```bash
# Create a profile
mkdir -p ~/.relay/profiles.d
cat > ~/.relay/profiles.d/default.yaml <<'YAML'
capabilities:
  - name: chat.ai
    handler: /opt/relay/handlers/chat-ai.sh
YAML

# Validate and publish (copies to node.yaml atomically)
node-cli capabilities validate ~/.relay/profiles.d/default.yaml
node-cli capabilities publish default
```

The daemon only reads `~/.relay/node.yaml`. Working profiles in
`~/.relay/profiles.d/` are never touched by the daemon at runtime.

## Managing node status

Use the CLI to temporarily set the node status:

```bash
# Mark the node as busy (stops claiming new stages)
node-cli node busy

# Mark as idle (available but explicitly idle)
node-cli node idle

# Clear the operator-requested status (return to automatic behaviour)
node-cli node clear-status

# Show current status (local + from server)
node-cli node status
```

All commands also support `--json` for programmatic use and `--once` to
send the status change immediately instead of waiting for the next heartbeat.

The status value is written directly into `node.yaml` using text
manipulation (regex), preserving your file's formatting, comments and
key ordering. No YAML re-serialisation takes place.

## Migration from `capabilities.active.yaml`

If you have an existing `~/.relay/capabilities.active.yaml` file, the
daemon **automatically copies** it to `~/.relay/node.yaml` on first start.
The old file is left in place for backward compat during rolling updates.

The same migration applies to:
- `~/.relay/capabilities.active.profile` → `~/.relay/node.profile`
- `~/.relay/capabilities.d/` → `~/.relay/profiles.d/`

After verifying everything works you can safely remove the old files:

```bash
rm ~/.relay/capabilities.active.yaml
rm ~/.relay/capabilities.active.profile
rm -rf ~/.relay/capabilities.d
```

## Validation

Validate any YAML file against the node schema:

```bash
node-cli capabilities validate ~/.relay/node.yaml
node-cli capabilities validate ~/.relay/profiles.d/default.yaml
```

This checks structure, types, required fields and flags unknown keys.
The daemon also validates on every profile publish.

## File reference

| Path | Purpose |
|------|---------|
| `~/.relay/node.yaml` | Active node config (daemon reads this) |
| `~/.relay/node.profile` | Name of the active profile (auto-generated) |
| `~/.relay/profiles.d/` | Working profiles (edited by operator) |
| `~/.relay/relay_config.json` | Daemon settings (base URL, intervals, etc.) |
