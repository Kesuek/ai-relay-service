# AI Relay Storage Node

KI-loser Storage-Service als Relay-Node. Registriert sich am Relay mit Storage-Capabilities, schreibt Dateien auf ein NAS-Mount und kann Service-Tasks an das Relay posten.

## Capabilities

- `storage.archive` — verschiebt Artefakte vom Relay in das NAS-Storage
- `storage.list` — listet archivierte Dateien auf dem NAS
- `storage.delete` — löscht archivierte Dateien
- `storage.quota` — meldet Speicherplatz-Status

## Schnelle Startanleitung

### 1. Image bauen

```bash
cd nodes/storage-node
docker build -t ai-relay-storage-node:latest .
```

### 2. Auf der NAS ausführen

```bash
docker run -d \
  --name ai-relay-storage \
  -v /volume1/ai-relay-storage:/storage \
  -v ai-relay-agent-config:/root/.relay \
  -e RELAY_BASE_URL=http://192.168.2.100:8788 \
  -e RELAY_NODE_NAME=nas-storage-01 \
  -e RELAY_STORAGE_PATH=/storage \
  -e RELAY_POLL_INTERVAL=8 \
  -e RELAY_QUOTA_THRESHOLD=0.85 \
  --restart unless-stopped \
  ai-relay-storage-node:latest
```

### 3. Erstmalige Registrierung

Falls die Node noch nicht registriert ist:

```bash
docker exec ai-relay-storage python /app/register.py
```

### 4. Node am Relay approven

Falls die Node mit pending-Status registriert, musst du sie im Dashboard oder via Admin-API approven:

```bash
curl -H "Authorization: Bearer $ADMIN_TOKEN" \
  -X POST \
  http://192.168.2.100:8788/relay/v2/admin/nodes/<node_id>/approve \
  -d '{"role":"service","capabilities":[{"name":"storage.archive","version":"1.0.0"}]}'
```

## Worker-Integration: Upload → artifact_id → Task

### Schritt 1: Datei an Relay hochladen

Ein Worker (z.B. Mac-Worker mit `mflux`) postet das generierte Bild an den Relay-Storage-Upload:

```bash
curl -H "Authorization: Bearer $WORKER_TOKEN" \
  -F "file=@generated_image.png" \
  http://192.168.2.100:8788/relay/v2/storage/upload
```

Antwort:

```json
{
  "artifact_id": "art_abc123",
  "name": "generated_image.png",
  "path": "/tmp/...",
  "size_bytes": 123456,
  "mime_type": "image/png",
  "created_by": "C9CGDMHK"
}
```

### Schritt 2: Task mit storage.archive Stage posten

```bash
curl -H "Authorization: Bearer $WORKER_TOKEN" \
  -X POST \
  http://192.168.2.100:8788/relay/v2/scheduler/tasks \
  -d '{
    "task_name": "archive_mflux_image",
    "stages": [
      {
        "stage_name": "archive",
        "capability": "storage.archive",
        "payload": {
          "artifact_id": "art_abc123",
          "target_path": "mac-worker/2026/06/21/sunset_768x768.png",
          "tags": ["mflux", "image_gen"]
        }
      }
    ]
  }'
```

### Schritt 3: Storage-Node übernimmt

Die Storage-Node claimt die Stage automatisch:

1. Lädt `art_abc123` von `GET /relay/v2/storage/files/{artifact_id}` herunter
2. Schreibt sie nach `/storage/mac-worker/2026/06/21/sunset_768x768.png`
3. Meldet die Stage als complete

### Schritt 4: Resultat nutzen

Der Worker bekommt über den Task-Status die `nas_path` zurück. Andere Nodes können die Datei später über die Storage-Node-Capabilities `storage.read` oder `storage.list` wieder finden (sofern das Relay eine passende Task dafür routed).

## Download über das Relay

Jeder berechtigte Node kann das Artifact über das Relay herunterladen:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://192.168.2.100:8788/relay/v2/storage/files/art_abc123 \
  -o downloaded_image.png
```

Metadaten:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://192.168.2.100:8788/relay/v2/storage/files/art_abc123/meta
```

## Service-Tasks von der Storage-Node

Die Node postet selbst Tasks ans Relay, wenn eine KI-Entscheidung nötig ist. Beispiel: Speicherplatz zu knapp.

```json
{
  "task_name": "storage.cleanup_request.123456",
  "stages": [
    {
      "stage_name": "decide",
      "capability": "llm.decide_cleanup",
      "payload": {
        "storage_path": "/storage",
        "usage_ratio": 0.91,
        "threshold": 0.85
      }
    }
  ]
}
```

Eine KI-Node (z.B. dein Haupt-Hermes) kann den Task claimen und zurückgeben:

```json
{
  "files_to_delete": [
    "mac-worker/2026/05/old_run_001.png"
  ]
}
```

Das Relay kann dann eine Folge-Stage `storage.delete` routen, die die Storage-Node ausführt.

## Docker Compose

Siehe [`docker-compose.yml`](docker-compose.yml).

## systemd

Siehe [`ai-relay-storage.service`](ai-relay-storage.service).
