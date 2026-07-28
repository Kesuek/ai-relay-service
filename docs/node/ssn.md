# Server-Side Node (SSN)

> **Status: umgesetzt mit T-069 (SSN-Daemon) + T-075 (Dynamic Routes) + T-076 (SSN Proxy).**

## Was ist ein SSN?

Ein **Server-Side Node (SSN)** ist ein normaler `node-cli` daemon, der auf dem
**gleichen Host läuft wie der Relay-Server**. Er heartbeatet Capabilities, claimt
Tasks und completed sie — genau wie jeder andere Worker-Node. Der Unterschied:
er braucht keinen externen Netzwerk-Port, weil er über localhost
(`http://127.0.0.1:8788`) mit dem Relay kommuniziert.

SSNs füllen die Lücke zwischen dem Relay-Core und externen Worker-Nodes. Sie
bieten Dienste an, die niedrige Latenz, direkten Zugriff auf die Relay-internen
APIs oder die Fähigkeit brauchen, andere Nodes zu orchestrieren — ohne einen
öffentlichen Endpunkt zu exponieren.

## Capability: `ssn.capability-pages`

Der Referenz-SSN heartbeatet die Capability `ssn.capability-pages` und
signalisiert damit: "Ich kann HTML-Dashboard-Seiten für andere Capabilities
hosten." Externe Worker-Nodes (z.B. ein Mac) verwalten ihre HTML-Seiten, indem
sie Tasks an diese Capability senden — der SSN führt den Handler aus und cached
die HTML lokal unter `~/.ssn/pages/<capability>.html`.

### Flow

1. **SSN heartbeatet** `ssn.capability-pages` — der Relay behandelt ihn wie
   jeden anderen Node.
2. **Worker will eine Dashboard-Seite deployen**: Worker lädt die HTML per
   `node-cli artifact upload` hoch, schickt dann einen Task an
   `ssn.capability-pages` mit `{"action":"add","capability":"image.generate.mflux","artifact_id":"artifact_xxx"}`.
3. **SSN claimt den Task**, führt `ssn-capability-pages.sh` aus, lädt das
   Artifact per `node-cli artifact download` herunter und speichert es als
   `~/.ssn/pages/image.generate.mflux.html`.
4. **Dashboard** zeigt in der **Capabilities**-Liste an, dass ein SSN-Node
   `ssn.capability-pages` anbietet.

### HTML-Verwaltung per Task

| Aktion | Task-Payload | Beschreibung |
|--------|-------------|--------------|
| **add** | `{"action": "add", "capability": "image.generate.mflux", "artifact_id": "artifact_xxx"}` | SSN lädt das Artifact herunter und speichert es als `<capability>.html` |
| **update** | `{"action": "update", "capability": "image.generate.mflux", "artifact_id": "artifact_yyy"}` | SSN ersetzt die bestehende HTML durch die neue |
| **delete** | `{"action": "delete", "capability": "image.generate.mflux"}` | SSN löscht die HTML-Datei |
| **list** | `{"action": "list"}` | SSN antwortet mit `{"capabilities": ["image.generate.mflux", …]}` |

## SSN Proxy (T-076)

Seit T-076 läuft auf dem SSN-Host ein **SSN Proxy** — ein HTMX-Server auf
`127.0.0.1:8790`. Er heartbeatet seine Endpoints als **Dynamic Routes**
(T-075) und macht alle Relay-Interaktionen serverseitig mit dem SSN-Node-Token.

### Architektur

```
Browser (Dashboard iFrame)
       │
       │ Session-Cookie
       ▼
Relay (192.168.2.60:8788)
       │
       │ Prüft Auth → leitet an Dynamic Route weiter
       ▼
SSN Proxy (127.0.0.1:8790)
       │
       │ SSN-Node-Token
       ▼
Relay (127.0.0.1:8788)
```

**Kein Session-Cookie für task-submit oder storage.** Der Browser schickt das
Session-Cookie nur an den Relay. Der Relay prüft die Berechtigung und leitet
intern an den SSN-Proxy weiter. Der SSN-Proxy injectet seinen Node-Token und
macht den eigentlichen API-Call.

### Endpoints

| Pfad | Methode | Beschreibung |
|------|---------|-------------|
| `/api/task-submit` | POST | Task an Relay submiten (mit SSN-Node-Token) |
| `/api/tasks/{id}` | GET | Task-Status vom Relay abfragen |
| `/api/storage/{id}` | GET | Artifact vom Relay herunterladen |
| `/mflux` | GET | mflux Capability Page (HTMX) |
| `/mflux/generate` | POST | Bild generieren (Task submit → pollen → Ergebnis) |
| `/mflux/bilder/{id}` | GET | Gecachtes Bild serven |

### Dynamic Routes

Der SSN-Proxy heartbeatet seine 3 API-Endpoints als Dynamic Routes in der
Capability-YAML (`~/.relay/capabilities.d/ssn.yaml`):

```yaml
capabilities:
  - name: ssn.capability-pages
    version: "1.0.0"
    routes:
      - path: /api/task-submit
        method: POST
        auth: session
        upstream: http://127.0.0.1:8790/api/task-submit
      - path: /api/tasks/{id}
        method: GET
        auth: session
        upstream: http://127.0.0.1:8790/api/tasks/{id}
      - path: /api/storage/{id}
        method: GET
        auth: session
        upstream: http://127.0.0.1:8790/api/storage/{id}
```

Die Routes sind erreichbar unter:
```
/relay/v2/dashboard/api/node-routes/{node_id}/api/task-submit
/relay/v2/dashboard/api/node-routes/{node_id}/api/tasks/{id}
/relay/v2/dashboard/api/node-routes/{node_id}/api/storage/{id}
```

### Capability Pages mit HTMX

Die Capability-Pages sind **reine HTML-Templates mit HTMX** — kein client-seitiges
JavaScript. HTMX ist eine ~14KB JS-Bibliothek, die aus HTML-Attributen AJAX-Requests
macht. Der Server returned HTML-Snippets.

**Vorteile:**
- Kein client-seitiges `fetch()` — keine CSRF-Probleme
- Kein Session-Cookie für API-Calls
- Bilder werden als Base64-Data-URL eingebettet (kein separater Image-Request)
- Einfache Formulare statt async-JS-Chaos

**Wichtig: Node-ID-agnostische Pfade**

Die HTML-Seite darf **keine absoluten Pfade** oder die node_id hardcoden.
Da die Dynamic Route die node_id im Pfad trägt
(`/api/node-routes/{node_id}/mflux`), müssen alle HTMX-Requests **relativ**
sein. Sonst brechen die Links, wenn der SSN eine neue node_id bekommt
(z.B. durch Re-Registrierung).

**Richtig (relativ):**
```html
<form hx-post="mflux/generate" hx-target="#result">
```

**Falsch (absolut):**
```html
<form hx-post="/mflux/generate" hx-target="#result">
```

Bilder werden als Base64-Data-URL direkt ins HTML eingebettet, statt über
einen separaten Image-Endpoint geladen. Das vermeidet einen weiteren
Request durch die Dynamic Route und macht die Seite unabhängig von der
node_id:

```python
import base64
img_b64 = base64.b64encode(img_data).decode()
html = f'<img src="data:image/png;base64,{img_b64}" alt="Bild">'
```

**Beispiel (mflux-Seite):**
```html
<form hx-post="/mflux/generate" hx-target="#result">
  <textarea name="prompt" required></textarea>
  <select name="format">
    <option value="quadrat">Quadrat (512×512)</option>
  </select>
  <button type="submit">✨ Generieren</button>
</form>
<div id="result"></div>
```

## Deployment

### 1. SSN-Daemon (T-069)

Siehe [setup.md](../server/setup.md) für die Server-Config (`ssn_enabled`,
`ssn_auto_approve`). Der SSN-Daemon wird als systemd-User-Unit gestartet:

```bash
cp systemd/ai-relay-ssn.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now ai-relay-ssn.service
```

### 2. SSN-Proxy (T-076)

```bash
cp systemd/ai-relay-ssn-proxy.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now ai-relay-ssn-proxy.service
```

### 3. Capabilities-Profil

```yaml
# ~/.relay/capabilities.d/ssn.yaml
capabilities:
  - name: ssn.capability-pages
    version: "1.0.0"
    type: native
    description: "Server-Side Node — hosts HTML dashboard pages"
    auto_publish: true
    claimable: true
    handler: /home/felix/projects/ai-relay-service/nodes/handlers/ssn-capability-pages.sh
    max_parallel: 1
    timeout: 300
    routes:
      - path: /api/task-submit
        method: POST
        auth: session
        upstream: http://127.0.0.1:8790/api/task-submit
      - path: /api/tasks/{id}
        method: GET
        auth: session
        upstream: http://127.0.0.1:8790/api/tasks/{id}
      - path: /api/storage/{id}
        method: GET
        auth: session
        upstream: http://127.0.0.1:8790/api/storage/{id}
```

Publizieren:
```bash
node-cli capabilities publish ssn
```

## Siehe auch

- [Capabilities](capabilities.md) — Capability-Namen, Suffixe, Handler-Contract, Dynamic Routes
- [node-cli-Referenz](cli-reference.md) — `task submit`, `artifact upload`, `artifact download`
- [Server-Setup](../server/setup.md) — `ssn_enabled`/`ssn_auto_approve` Config
