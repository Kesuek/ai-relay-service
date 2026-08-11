# Storage-Node auf QNAP Container Station

Der **Storage-Node** (`ai-relay-storage`) ist ein NAS-Storage-Dienst für den
AI-Relay-Service. Er speichert Dateien, verwaltet Backups und überträgt
Ordner als `.tar.gz` — ideal für eine QNAP als zentraler Storage.

Dieses Image ist für **x86_64 (Intel/AMD)** QNAP-Modelle gebaut.

## Voraussetzungen

- QNAP mit **Container Station** (QTS/QuTS hero)
- x86_64-CPU (Intel/AMD) — ARM-Modelle brauchen ein eigenes Image
- Ein laufender **Relay-Server** (der Storage-Node verbindet sich zu ihm)

## Installation

### 1. Image laden

**Variante A — direkt von GHCR (empfohlen):**

Das Image ist public auf GitHub Container Registry. Die QNAP kann es direkt
pullen — kein Login nötig:

```bash
docker pull ghcr.io/kesuek/ai-relay-storage:latest
```

**Variante B — aus dem Release-Asset:**

Lade das Release-Asset `ai-relay-storage-bundle.tar` von der
[Releases-Seite](https://github.com/Kesuek/ai-relay-service/releases) herunter
und lade es in Docker:

```bash
# Auf der QNAP (per SSH) oder in Container Station:
docker load -i ai-relay-storage-bundle.tar
```

Das Bundle enthält beide Images: `ai-relay-storage:latest` und
`ai-relay-node-base:latest`.

### 2. Storage-Node starten

**Variante A — per `docker run` (SSH):**

```bash
docker run -d \
  --name ai-relay-storage \
  --restart unless-stopped \
  -e RELAY_URL=http://<relay-ip>:8788 \
  -e NODE_NAME=storage-node \
  -e NODE_ENDPOINT=http://<qnap-ip>:8791 \
  -v /share/Container/ai-relay-storage:/storage \
  -v ai-relay-storage-state:/home/appuser/.relay \
  ghcr.io/kesuek/ai-relay-storage:latest
```

**Variante B — per Container Station (GUI):**

1. Öffne **Container Station** → **Übersicht** → **Erstellen** → **Image**.
2. Wähle `ghcr.io/kesuek/ai-relay-storage:latest` (oder `ai-relay-storage:latest` nach `docker load`).
3. Setze die Umgebungsvariablen (siehe Tabelle unten).
4. Mounte `/storage` auf einen NAS-Ordner (z.B. `/share/Container/ai-relay-storage`).
5. Starte den Container.

### 3. Node approven

Der Node registriert sich als `pending`. Approve ihn im Relay-Dashboard oder
per Admin-API:

```bash
curl -X POST http://<relay-ip>:8788/relay/v2/admin/nodes/<node_id>/approve \
  -H "Content-Type: application/json" \
  -d '{"role":"service","capabilities":[{"name":"storage.store","version":"1.0.0"}]}'
```

## Umgebungsvariablen

| Variable | Pflicht | Default | Beschreibung |
|----------|---------|---------|--------------|
| `RELAY_URL` | **ja** | — | Relay-Basis-URL, z.B. `http://192.168.1.50:8788` |
| `NODE_NAME` | nein | Hostname | Anzeigename im Dashboard |
| `NODE_ENDPOINT` | nein | — | Endpoint, über den der Relay den Node erreicht (für Bridge-Routen), z.B. `http://<qnap-ip>:8791` |
| `NODE_ROLE` | nein | `worker` | `service` für Storage (im Image gesetzt) |
| `NODE_REGISTRATION_SECRET` | nein | — | Vorab erstelltes `rs_...`-Secret für die Registrierung |
| `RELAY_SERVER_IP` | nein | aus RELAY_URL | Explizite Relay-Server-IP für die Bridge-Source-IP-Allowlist |
| `RELAY_STORAGE_PATH` | nein | `/storage` | Basis-Verzeichnis für Dateien (im Image gesetzt) |

## Volumes

| Mount | Zweck |
|-------|-------|
| `/storage` | NAS-Export — die eigentlichen Dateien/Backups. Bind-mount auf einen QNAP-Ordner. |
| `/home/appuser/.relay` | Node-Meta + Token (persistiert die Identität über Neustarts). Named Volume. |

> **⚠️ Wichtig für Updates:** Das Volume `ai-relay-storage-state` (→ `/home/appuser/.relay`)
> muss beim Neustart **gemountet bleiben**. Wenn du den Container löschst und neu erstellst,
> ohne das Volume zu mounten, verliert der Node seine `ai-relay-agent.json` (node_id + token)
> und registriert sich **neu** — er bekommt eine neue Node-ID und muss erneut approved werden.
> Beim `docker run` immer `-v ai-relay-storage-state:/home/appuser/.relay` mitgeben.

## Capabilities

Der Storage-Node bietet:

- **Dateien:** `storage.store` / `fetch` / `delete` / `list` / `quota` / `stat` / `move`
- **Große Dateien:** `storage.upload_channel` / `storage.download_channel` (Bridge-Routen)
- **Backups:** `backup.create` / `list` / `info` / `restore` / `delete` / `retention`
- **Ordner:** `storage.extract` / `storage.archive` (`.tar.gz`)

## Troubleshooting

- **`Connection refused` beim Start:** Der Relay ist nicht erreichbar. Prüfe `RELAY_URL` und dass der Relay läuft.
- **Node bleibt `pending`:** Noch nicht approved. Approve im Dashboard.
- **Bridge-Routen funktionieren nicht:** Setze `RELAY_SERVER_IP` explizit, wenn die QNAP den Relay nicht per DNS auflöst.
- **Dateien landen nicht auf der NAS:** Prüfe den `/storage`-Mount (muss auf einen echten QNAP-Ordner zeigen).

## Quellcode

Der Storage-Node lebt im Repo unter `docker/nodes/storage/`. Das Basis-Image
unter `docker/nodes/base/`. Siehe `docs/node/storage.md` für die volle
Architektur.
