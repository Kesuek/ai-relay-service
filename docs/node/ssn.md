# Server-Side Node (SSN)

> **Status: umgesetzt mit T-069.**

## Was ist ein SSN?

Ein **Server-Side Node (SSN)** ist ein normaler `node-cli` daemon, der auf dem **gleichen Host läuft wie der Relay-Server**. Er heartbeatet Capabilities, claimt Tasks und completed sie — genau wie jeder andere Worker-Node. Der Unterschied: er braucht keinen externen Netzwerk-Port, weil er über localhost (`http://127.0.0.1:8788`) mit dem Relay kommuniziert.

SSNs füllen die Lücke zwischen dem Relay-Core und externen Worker-Nodes. Sie bieten Dienste an, die niedrige Latenz, direkten Zugriff auf die Relay-internen APIs oder die Fähigkeit brauchen, andere Nodes zu orchestrieren — ohne einen öffentlichen Endpunkt zu exponieren. Im Relay selbst ist der SSN **kein Sonderfall**: er registriert sich wie jeder Worker, heartbeatet wie jeder Worker und bekommt Tasks zugewiesen wie jeder Worker. Es gibt kein Proxy, kein Spezial-Routing, keine Relay-internen Handler für SSN-Capabilities.

## Capability: `ssn.capability-pages`

Der Referenz-SSN heartbeatet die Capability `ssn.capability-pages` und signalisiert damit: "Ich kann HTML-Dashboard-Seiten für andere Capabilities hosten." Externe Worker-Nodes (z.B. ein Mac) verwalten ihre HTML-Seiten, indem sie Tasks an diese Capability senden — der SSN führt den Handler aus und cached die HTML lokal unter `~/.ssn/pages/<capability>.html`.

### Flow

1. **SSN heartbeatet** `ssn.capability-pages` — der Relay behandelt ihn wie jeden anderen Node.
2. **Worker will eine Dashboard-Seite deployen**: Worker lädt die HTML per `node-cli artifact upload` hoch, schickt dann einen Task an `ssn.capability-pages` mit `{"action":"add","capability":"image.generate.mflux","artifact_id":"artifact_xxx"}`.
3. **SSN claimt den Task**, führt `ssn-capability-pages.sh` aus, lädt das Artifact per `node-cli artifact download` herunter und speichert es als `~/.ssn/pages/image.generate.mflux.html`.
4. **Dashboard** zeigt in der **Capabilities**-Liste an, dass ein SSN-Node `ssn.capability-pages` anbietet.
5. **Operator/Admin** öffnet die vom SSN gehostete HTML-Seite (der SSN servt sie auf einem eigenen lokalen HTTP-Endpunkt oder gibt sie über ein Task-Result zurück).
6. **Klick auf Generieren** in der HTML → Task an die eigentliche Worker-Capability (z.B. `image.generate.mflux`) → Worker erzeugt das Bild → Artifact → SSN lädt es herunter und zeigt es an.

Der Relay bleibt ahnungslos — er matched nur Tasks an `ssn.capability-pages` wie an jede andere Capability.

### HTML-Verwaltung per Task

Externe Worker-Nodes (z.B. der Mac) verwalten die HTML-Seiten über Tasks an `ssn.capability-pages`:

| Aktion | Task-Payload | Beschreibung |
|--------|-------------|--------------|
| **add** | `{"action": "add", "capability": "image.generate.mflux", "artifact_id": "artifact_xxx"}` | SSN lädt das Artifact herunter und speichert es als `<capability>.html` |
| **update** | `{"action": "update", "capability": "image.generate.mflux", "artifact_id": "artifact_yyy"}` | SSN ersetzt die bestehende HTML durch die neue |
| **delete** | `{"action": "delete", "capability": "image.generate.mflux"}` | SSN löscht die HTML-Datei |
| **list** | `{"action": "list"}` | SSN antwortet mit `{"capabilities": ["image.generate.mflux", …]}` |

Der Worker uploaded die HTML zuerst per `node-cli artifact upload` und schickt dann einen Task an `ssn.capability-pages` mit der `artifact_id`. Der SSN lädt das Artifact herunter, cached es lokal und servt es.

### Handler

Der Handler liegt unter `nodes/handlers/ssn-capability-pages.sh`. Er ist ein reines Shell-Skript und hält sich an den [Handler-Contract](capabilities.md#handler-contract): stdin = Payload-JSON, stdout = Result-JSON, env = `RELAY_BASE_URL`/`RELAY_TOKEN_FILE`/…. Für `add`/`update` ruft er `python3 -m nodes.common.node_cli artifact download` auf, sodass der Download über die authentifizierte Relay-Session des SSN läuft.

### Vorteile

- **Kein externer Port** — SSN kommuniziert über localhost.
- **Kein Proxy im Relay** — der Relay matched nur Tasks.
- **Node hat volle Kontrolle** — Submit, Poll, Artifact-Download alles über `node-cli`.
- **Skaliert** — beliebig viele Dashboard-Seiten, jede Capability kann eine haben.
- **Konsistente Auth** — der Relay macht Auth, der SSN bekommt nur authentifizierte Requests.

## Deployment

### 1. Capabilities-Profil für den SSN

Lege ein Profil an (z.B. `~/.relay/capabilities.d/ssn.yaml`):

```yaml
capabilities:
  - name: ssn.capability-pages
    version: "1.0.0"
    type: tool
    description: "Hosts HTML dashboard pages for other capabilities."
    auto_publish: true
    claimable: true
    handler: /home/felix/projects/ai-relay-service/nodes/handlers/ssn-capability-pages.sh
    max_parallel: 1
    timeout: 300
```

Publish mit `node-cli capabilities publish ssn`.

### 2. systemd-User-Unit

Das Repo enthält `systemd/ai-relay-ssn.service`:

```ini
[Unit]
Description=AI Relay SSN — Server-Side Node
After=ai-relay-service.service
BindsTo=ai-relay-service.service

[Service]
Type=simple
ExecStart=%h/projects/ai-relay-service/.venv/bin/python -m nodes.common.node_cli daemon foreground
WorkingDirectory=%h/projects/ai-relay-service
Restart=always
Environment=RELAY_BASE_URL=http://127.0.0.1:8788

[Install]
WantedBy=default.target
```

Installieren mit:

```bash
cp systemd/ai-relay-ssn.service ~/.config/systemd/user/
systemctl --user daemon-reload
```

### 3. Server-Config

In `~/.relay/config.yaml`:

```yaml
ssn_enabled: true
ssn_auto_approve: true        # SSN-Registrierung automatisch approven
ssn_service_unit: "ai-relay-ssn.service"
```

- `ssn_enabled: true` — der Relay-Server startet/stoppt die systemd-Unit des SSN in `lifespan()`.
- `ssn_auto_approve: true` — der Relay approve die SSN-Registrierung automatisch, damit der SSN ohne manuellen Admin-Schritt online gehen kann.

Alternativ als Env-Vars: `RELAY_SSN_ENABLED=true`, `RELAY_SSN_AUTO_APPROVE=true`.

### 4. Registrierung

Beim ersten Start registriert sich der SSN wie jeder Worker (`node-cli` liest `~/.relay/relay_config.json` für die `base_url`). Mit `ssn_auto_approve: true` approvt der Maintenance-Loop die Registrierung automatisch; der SSN geht mit dem nächsten Heartbeat auf `online`. Ohne Auto-Approve musst du den Node im Dashboard unter **Admin → Nodes** manuell approven.

Der SSN braucht ein gültiges `~/.relay/ai-relay-agent.json` (Registrierungs-Metadaten) und ein Runtime-Token. Nach der Registrierung liegen beide in `~/.relay/`.

## Siehe auch

- [Capabilities](capabilities.md) — Capability-Namen, Suffixe, Handler-Contract
- [node-cli-Referenz](cli-reference.md) — `task submit`, `artifact upload`, `artifact download`
- [Server-Setup](../server/setup.md) — `ssn_enabled`/`ssn_auto_approve` Config