# Token & Credential Lifecycle

The relay uses several credential families, distinguished by their prefix.
This document explains their lifetimes, how to refresh them, and how to
recover when one is lost.

## Token types

| Credential | Prefix | Default TTL | Purpose |
|---|---|---|---|
| Master admin seed | `adm_` | Permanent (until rotated) | Bootstrap & recovery — login when no human admin exists |
| Bootstrap seed | `bs_` | 24 h | One-time bootstrap session after master-seed login |
| Temporary token | `tp_` | 24 h | Issued on registration, replaced after approval |
| Runtime token | `rt_` | 7 days | Day-to-day auth for heartbeat, claim, complete |
| Registration secret | `rs_` | 12 h | Recovery only — rotate the runtime token |

One runtime token per node. Refreshing it invalidates the previous one.

The master admin seed and bootstrap seed are node-admin credentials managed
on the relay host (see [../concepts.md](../concepts.md) and
[../server/admin.md](../server/admin.md)); nodes only use the `tp_`, `rt_`,
and `rs_` credentials.

## Lifecycle

```
[Register] → temporary token (24h) + registration secret (12h)
       ↓
[Admin approves] → runtime token (7 days), node status: approved
       ↓
[Heartbeat every 8s] → status online → claim → work → complete
       ↓
[Before expiry] → POST /auth/refresh → new runtime token
       ↓
[Lost runtime token] → POST /auth/refresh with registration_secret
                     → new runtime token + new registration secret
```

If both the runtime token **and** the registration secret expired, the node
must be re-registered.

## Check lifetimes (read-only)

`/relay/v2/auth/status` reports lifetimes but never issues tokens:

```bash
curl -X POST "http://${RELAY_HOST}:8788/relay/v2/auth/status" \
  -H "Authorization: Bearer rt_..." \
  -H "Content-Type: application/json" \
  -d '{"node_id": "V34ETT74"}'
```

```json
{
  "node_id": "V34ETT74",
  "status": "approved",
  "rt_valid_until": "2026-06-30T03:41:23+00:00",
  "rs_valid_until": "2026-06-23T15:41:23+00:00",
  "message": "Credential status"
}
```

Before approval, poll **unauthenticated** with the registration secret:

```bash
curl -X POST "http://${RELAY_HOST}:8788/relay/v2/auth/status" \
  -H "Content-Type: application/json" \
  -d '{"node_id": "V34ETT74", "registration_secret": "rs_..."}'
```

## Refresh the runtime token

```bash
curl -X POST "http://${RELAY_HOST}:8788/relay/v2/auth/refresh" \
  -H "Authorization: Bearer rt_..." \
  -H "Content-Type: application/json" \
  -d '{"requested_credential": "runtime_token"}'
```

Save the new token immediately — the old one is invalidated.

## Refresh the registration secret

```bash
curl -X POST "http://${RELAY_HOST}:8788/relay/v2/auth/refresh" \
  -H "Authorization: Bearer rt_..." \
  -H "Content-Type: application/json" \
  -d '{"requested_credential": "registration_secret"}'
```

## Recover a lost runtime token

If the runtime token was lost, use the registration secret. The response
contains a new runtime token **and a new registration secret** — the old
registration secret is rotated, so persist both immediately:

```bash
curl -X POST "http://${RELAY_HOST}:8788/relay/v2/auth/refresh" \
  -H "Content-Type: application/json" \
  -d '{
    "node_id": "V34ETT74",
    "registration_secret": "rs_...",
    "requested_credential": "runtime_token"
  }'
```

```python
data = r.json()
save_token(data["token"])                              # ai-relay-agent.token
state["registration_secret"] = data["registration_secret"]
STATE_FILE.write_text(json.dumps(state, indent=2))     # ai-relay-agent.json
```

> Only `/relay/v2/auth/refresh` creates or rotates credentials. `/auth/status`
> only reports lifetimes. A recovery via registration secret rotates the
> registration secret; persist the new one immediately.

## State file schema

`~/.relay/ai-relay-agent.json`:

```json
{
  "node_id": "V34ETT74",
  "node_name": "my-node",
  "endpoint": "http://192.168.1.60:9000",
  "registration_secret": "rs_...",
  "capabilities": [{"name": "chat", "version": "1.0.0"}],
  "base_url": "http://192.168.1.50:8788"
}
```

The runtime token lives separately in `~/.relay/ai-relay-agent.token` so it can
be rotated without rewriting the state file.

## Common mistakes

| Mistake | Fix |
|---|---|
| Runtime token expired | Refresh via `/auth/refresh`. If lost, recover with the registration secret. |
| Both credentials expired | Re-register the node. |
| Calling `/auth/status` to rotate | Use `/auth/refresh` for rotation. |
| Re-registering with the same `node_id` | 409 Conflict — recover the token instead. |

## Automatic token cleanup

The relay runs a background watchdog every hour that deletes expired tokens
from the database (`DELETE FROM node_tokens WHERE expires_at < ?`). This
prevents the token table from growing indefinitely. The cleanup is
transparent to nodes — a token that was already expired would be rejected
by the auth middleware regardless.
