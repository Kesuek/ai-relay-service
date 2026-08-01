# Node-Dokumentation: Zusammenfassung zu einem generischen Node-Setup-Guide

> **For OpenCode:** `opencode run --agent primary "Abarbeiten von .hermes/plans/2026-07-17_node-doku-generisch.md" --thinking`

**Goal:** Die Node-Dokumentation von 5 zersplitterten Dateien zu einem einzigen generischen Node-Setup-Guide zusammenfassen. Das Proxmox-Dokument wird zu einem kurzen Beispiel-Abschnitt degradiert. Die CLI-Reference und Capability-Reference bleiben als eigenständige Referenzdokumente erhalten.

**Architecture:** 
- `docs/node-operator/setup.md` — **NEU**, der zentrale Node-Setup-Guide (generisch, plattformunabhängig)
- `docs/node-operator/node-cli-reference.md` — bleibt als CLI-Reference
- `docs/node-operator/capabilities.md` — bleibt als Capability-Reference
- `docs/node-operator/proxmox-worker-setup.md` — wird stark gekürzt zu einem "Example: Proxmox LXC"-Abschnitt in setup.md, dann gelöscht
- `docs/node-readme.md` — wird durch einen Redirect/Summary ersetzt, der auf setup.md verweist
- `docs/nodes-design.md` — bleibt (Architektur-Doku)
- `nodes/common/README.md` — bleibt (Poller-Referenz für Entwickler)
- `AGENT_README.md` — wird durch einen Redirect auf setup.md ersetzt
- `README.md` — Doc-Tabelle aktualisieren

**Tech Stack:** Markdown

---

## Task 1: Bestandsaufnahme — welche Inhalte aus welcher Datei wandern wohin

**Objective:** Alle existierenden Node-Dokumente analysieren und entscheiden, welche Inhalte in den neuen generischen Guide wandern.

**Analyse (bereits gemacht):**

| Datei | Inhalt | Verbleib |
|-------|--------|----------|
| `docs/node-readme.md` | Protokoll-Ebene (Registration, Heartbeat, Claim, Complete, Artifacts) via curl. Checkliste für neuen Node. | Wird in `setup.md` integriert. `node-readme.md` wird zu einem kurzen Summary, das auf `setup.md` verweist. |
| `docs/node-operator/proxmox-worker-setup.md` | LXC-spezifisches Setup (pct create, systemd, keyctl). | Wird zu einem "Example: Proxmox LXC"-Abschnitt in `setup.md` (max 30 Zeilen). Rest gelöscht. |
| `docs/node-operator/capabilities.md` | Capability-Formate, Suffixe, Handler-Contract, node-cli profile flow. | Bleibt als Referenz. Wird in `setup.md` verlinkt. |
| `docs/node-operator/node-cli-reference.md` | Vollständige CLI-Reference (530 Zeilen). | Bleibt als Referenz. Wird in `setup.md` verlinkt. |
| `docs/node-operator/token-lifecycle.md` | Token-Typen, Refresh, Recovery. | Bleibt. Wird in `setup.md` verlinkt. |
| `nodes/common/README.md` | Poller-Referenz (Bootstrap, Handler-Contract, Platform-Wrapper). | Bleibt (Entwickler-Doku). Wird in `setup.md` als "Advanced" verlinkt. |
| `AGENT_README.md` | Kurzform von node-readme. | Wird durch Redirect auf `setup.md` ersetzt. |
| `docs/nodes-design.md` | Architektur (KI-capable vs KI-less, Self-Care-Pattern). | Bleibt. Wird in `setup.md` verlinkt. |

---

## Task 2: `docs/node-operator/setup.md` erstellen — der zentrale Node-Setup-Guide

**Objective:** Ein neues, generisches Dokument, das den kompletten Node-Setup-Flow abdeckt — plattformunabhängig, ohne Proxmox-spezifische Details im Haupttext.

**Files:**
- Create: `docs/node-operator/setup.md`

**Gliederung:**

```markdown
# AI Relay — Node Setup Guide

Generic guide for setting up a worker or service node. Platform-independent.
For platform-specific examples see the [Examples](#examples) section at the end.

## 1. Prerequisites

- Relay URL (ask your admin or check mDNS: `http://ai-relay.local:8788`)
- Python 3.11+ (for the node-cli)
- Network access to the relay

## 2. Install the node-cli

### Option A: From the relay repository (recommended)

```bash
git clone https://github.com/Kesuek/ai-relay-service.git
cd ai-relay-service
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Option B: Standalone bundle

[Download the storage-node bundle or copy node_cli.py directly]

### Option C: Docker

[If a Docker image exists]

## 3. Register the node

Every node needs a relay account. Registration is a one-time HTTP call:

```bash
curl -X POST "http://${RELAY_HOST}:8788/relay/v2/auth/register" \
  -H "Content-Type: application/json" \
  -d '{
    "node_name": "my-node",
    "endpoint": null,
    "role": "worker",
    "capabilities": [{"name": "chat.ai", "version": "1.0.0"}]
  }'
```

Save the response — it contains `node_id`, `registration_secret` (`rs_...`), and a temporary token (`tp_...`).

Persist the credentials:

```bash
mkdir -p ~/.relay
echo '{"node_id": "...", "node_name": "my-node", "registration_secret": "...", "capabilities": [...], "base_url": "http://..."}' > ~/.relay/ai-relay-agent.json
```

## 4. Wait for admin approval

A newly registered node is `pending`. Poll the status endpoint until an admin approves it:

```bash
curl -X POST "http://${RELAY_HOST}:8788/relay/v2/auth/status" \
  -H "Content-Type: application/json" \
  -d '{"node_id": "...", "registration_secret": "..."}'
```

Expected: `{"status": "approved"}` or `{"status": "online"}`.

## 5. Obtain a runtime token

After approval, recover the runtime token using the registration secret:

```bash
curl -X POST "http://${RELAY_HOST}:8788/relay/v2/auth/refresh" \
  -H "Content-Type: application/json" \
  -d '{"node_id": "...", "registration_secret": "...", "requested_credential": "runtime_token"}'
```

Save the token:

```bash
echo "rt_..." > ~/.relay/ai-relay-agent.token
```

The response also contains a new `registration_secret` — update `ai-relay-agent.json`.

## 6. Define capabilities

Create a capability profile:

```bash
mkdir -p ~/.relay/capabilities.d
```

```yaml
# ~/.relay/capabilities.d/default.yaml
capabilities:
  - name: chat.ai
    version: "1.0.0"
    auto_publish: true
    claimable: true
    handler: /path/to/handler.sh
    max_parallel: 2
    timeout: 300
```

Validate and publish:

```bash
node-cli capabilities validate default
node-cli capabilities publish default
```

See [capabilities.md](capabilities.md) for the full profile format and handler contract.

## 7. Start the daemon

### Foreground (testing)

```bash
node-cli daemon foreground
```

Check `~/.relay/worker_status.json` — a fresh heartbeat means the node is `online`.

### systemd (Linux)

```ini
# /etc/systemd/system/ai-relay-worker.service
[Unit]
Description=AI Relay Worker Node
After=network-online.target

[Service]
Type=simple
User=felix
WorkingDirectory=/home/felix/ai-relay-service
ExecStart=/home/felix/ai-relay-service/.venv/bin/python -m nodes.common.node_cli daemon foreground
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ai-relay-worker.service
```

### launchd (macOS)

[Kurzes Beispiel, siehe nodes/common/com.example.ai-relay-agent.plist]

### Docker

[Wenn vorhanden]

## 8. Verify

```bash
node-cli status
# -> Shows last heartbeat, tasks completed, in-flight stages
```

In the relay dashboard the node should appear as `online`.

## 9. Token lifecycle

Runtime tokens expire after 7 days. The daemon refreshes them automatically.
See [token-lifecycle.md](token-lifecycle.md) for manual refresh and recovery.

## 10. Troubleshooting

| Problem | Solution |
|---------|----------|
| 401 on heartbeat | Token expired — daemon refreshes automatically. If manual: see token-lifecycle.md |
| 403 on claim | Capability not in latest heartbeat — check capabilities.active.yaml |
| Node stays pending | Admin has not approved it yet |
| Node offline | Daemon not running — check systemctl / launchctl |
| Both credentials expired | Re-register the node |

## Examples

### Proxmox LXC

[Kurze 20-30 Zeilen Zusammenfassung des Proxmox-Setups — nur die LXC-spezifischen Schritte]

## Next steps

- [node-cli-reference.md](node-cli-reference.md) — full command reference
- [capabilities.md](capabilities.md) — capability profiles & handler contract
- [token-lifecycle.md](token-lifecycle.md) — credential refresh & recovery
- [nodes-design.md](../nodes-design.md) — node architecture & self-care pattern
- [nodes/common/README.md](../../nodes/common/README.md) — poller reference (advanced)
```

---

## Task 3: `docs/node-readme.md` auf Summary kürzen

**Objective:** `node-readme.md` war der bisherige Node-Guide. Nachdem `setup.md` den kompletten Flow abdeckt, wird `node-readme.md` auf eine kurze Summary gekürzt, die auf `setup.md` verweist.

**Files:**
- Modify: `docs/node-readme.md`

**Neuer Inhalt (max 30 Zeilen):**

```markdown
# AI Relay — Node Connection Guide

> **This document is a quick reference. For the full step-by-step setup see
> [node-operator/setup.md](node-operator/setup.md).**

## Quick reference

| Step | What | Where |
|------|------|-------|
| 1 | Install the node-cli | `setup.md` §2 |
| 2 | Register the node | `setup.md` §3 |
| 3 | Wait for approval | `setup.md` §4 |
| 4 | Obtain runtime token | `setup.md` §5 |
| 5 | Define capabilities | `setup.md` §6 |
| 6 | Start the daemon | `setup.md` §7 |
| 7 | Verify | `setup.md` §8 |

## API endpoints (curl)

[Die curl-Beispiele für heartbeat, claim, complete, artifacts bleiben — das ist der Kern des Protokolls]

## Minimal worker (Python)

[Das minimal worker example aus dem alten node-readme bleibt]

## Next steps

- [node-operator/setup.md](node-operator/setup.md) — full setup guide
- [node-operator/node-cli-reference.md](node-operator/node-cli-reference.md) — CLI reference
- [node-operator/capabilities.md](node-operator/capabilities.md) — capability profiles
- [node-operator/token-lifecycle.md](node-operator/token-lifecycle.md) — token lifecycle
```

---

## Task 4: `AGENT_README.md` auf Summary kürzen

**Objective:** `AGENT_README.md` war die Kurzform von `node-readme.md`. Wird ebenfalls auf eine Summary mit Verweis auf `setup.md` gekürzt.

**Files:**
- Modify: `AGENT_README.md`

**Neuer Inhalt (max 20 Zeilen):**

```markdown
# Agent / Node Connection Guide

> **This document is a quick reference. For the full step-by-step setup see
> [docs/node-operator/setup.md](docs/node-operator/setup.md).**

[Kurze curl-Beispiele für register, heartbeat, claim, complete]

## Next steps

- [docs/node-operator/setup.md](docs/node-operator/setup.md) — full setup guide
- [docs/node-operator/node-cli-reference.md](docs/node-operator/node-cli-reference.md) — CLI reference
```

---

## Task 5: `docs/node-operator/proxmox-worker-setup.md` kürzen und in setup.md integrieren

**Objective:** Das Proxmox-Dokument auf ~30 Zeilen kürzen und als "Example: Proxmox LXC"-Abschnitt in `setup.md` einfügen. Danach die alte Datei löschen.

**Files:**
- Modify: `docs/node-operator/setup.md` (Example-Abschnitt ergänzen)
- Delete: `docs/node-operator/proxmox-worker-setup.md`

**Gekürzter Inhalt für den Example-Abschnitt:**

```markdown
### Proxmox LXC

Create a Debian 12 privileged container (unprivileged needs `keyctl=1`):

```bash
pct create 110 debian-12-standard --hostname ai-relay-worker \
  --cores 2 --memory 2048 --rootfs local-lvm:10 \
  --net0 name=eth0,bridge=vmbr0,ip=192.168.2.50/24,gw=192.168.2.1 \
  --unprivileged 0
pct start 110 && pct enter 110
```

Inside the container: install Python, clone the repo, install deps, register, and start the daemon as described in §2–7 above. The only LXC-specific requirement is a **privileged** container (or `keyctl=1` for unprivileged) because `python-keyring` needs `keyctl`.
```

---

## Task 6: `README.md` Doc-Tabelle aktualisieren

**Objective:** Die Doc-Tabelle im README.md muss die neue Struktur abbilden.

**Files:**
- Modify: `README.md`

**Änderungen:**
- `node-readme` bleibt (zeigt jetzt die gekürzte Version)
- `node-cli-reference` bleibt (bereits in Task 7 des vorherigen Plans ergänzt)
- `proxmox-worker-setup` entfernen (existiert nicht mehr)
- `node-setup` hinzufügen → `/relay/v2/docs/node-setup` → "Full node setup guide" → Node operator

---

## Task 7: Tests laufen lassen

**Objective:** Sicherstellen, dass keine Code-Änderungen die Tests brechen.

**Files:**
- Keine

**Step 1: Tests ausführen**

```bash
cd ~/projects/ai-relay-service
source .venv/bin/activate
python -m pytest tests/ -q
```

Expected: ALL PASSED

---

## Abschliessende Antwort für das Project Board

**TASKS.md:**
- T-031 — "Node-Dokumentation: Zusammenfassung zu generischem Node-Setup-Guide" — Prio MID, Status done

**DECISIONS.md:**
- Eintrag: "2026-07-17: Node-Dokumentation generisch gemacht — setup.md neu, proxmox-worker-setup gelöscht, node-readme/AGENT_README auf Summary gekürzt"

**PLAN.md:**
- Phase 6 bleibt ✅

**IDEAS.md:**
- Umgesetzte Idee ergänzen

---

## OpenCode-Output

```
.hermes/opencode-output/2026-07-17_node-doku-generisch/
├── STATUS.md
├── TASKS.md
├── DECISIONS.md
├── VERIFICATION.md
└── LOG.md
```
