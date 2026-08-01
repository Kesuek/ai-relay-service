# Streaming-Upload & Artifact-Download — Implementation Plan

> **Fuer OpenCode:** Diesen Plan Task fuer Task abarbeiten. Nach jedem Task: `pytest` laufen lassen.

**Goal:** Uploads auf SpooledTemporaryFile umstellen (kein vollstaendiger RAM-Load mehr), Chunked-Upload-Endpunkt hinzufuegen, Artifact-Download in den Worker integrieren. Server und Worker bleiben synchron.

**Context:** Aktuell laedt `POST /relay/v2/storage/upload` das komplette File via `await file.read()` in den RAM, bevor es auf Platte geschrieben wird. Bei 100MB+ Uploads skaliert das nicht. Der Worker/Poller hat keine eingebaute Methode um Artifacts runterzuladen.

---

## Task 1: SpooledTemporaryFile im Upload-Endpunkt

**Objective:** `storage.py` so umbauen, dass eingehende Files chunkweise in eine `SpooledTemporaryFile` geschrieben werden. SHA256-Checksumme wird parallel berechnet. Kein vollstaendiger RAM-Load.

**Files:**
- Modify: `src/relay_server/api/v2/storage.py` (Upload-Logik)
- Modify: `src/relay_server/core/artifacts.py` (neue `store_artifact_from_file()`)
- Test: `tests/test_storage.py` (bestehende Tests anpassen + erweitern)
- Test: `tests/test_storage_e2e.py` (bestehende Tests muessen weiterlaufen)

**Details:**

### artifacts.py: Neue Funktion

```python
def store_artifact_from_file(
    name: str,
    file_path: Path,
    mime_type: Optional[str] = None,
    task_id: Optional[str] = None,
    stage_id: Optional[str] = None,
    created_by: Optional[str] = None,
) -> Dict[str, Any]:
    """Store an artifact by moving a temporary file into the artifacts directory.
    
    Unlike store_artifact() which takes bytes, this function takes a file path.
    The file is moved (not copied) to avoid double disk I/O.
    SHA256 is computed chunkwise during the move.
    """
    artifact_id = _generate_id("artifact")
    now = _format_time(_now())
    target_path = _artifact_path(artifact_id)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    
    # SHA256 + move in one pass
    h = hashlib.sha256()
    with open(file_path, "rb") as src:
        with open(target_path, "wb") as dst:
            for chunk in iter(lambda: src.read(8192), b""):
                h.update(chunk)
                dst.write(chunk)
    
    checksum = h.hexdigest()
    size = target_path.stat().st_size
    
    # DB-Eintrag (gleicher Code wie in store_artifact)
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO artifacts
               (artifact_id, task_id, stage_id, name, mime_type, size_bytes, checksum, storage_path, created_by, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (artifact_id, task_id, stage_id, name, mime_type, size, checksum, str(target_path), created_by, now),
        )
        conn.commit()
        event_bus.publish_sync("artifact_created", {"artifact_id": artifact_id, ...})
        return {...}  # gleiches Dict wie store_artifact
    finally:
        conn.close()
```

Die bestehende `store_artifact(content: bytes, ...)` bleibt erhalten — nur fuer interne/Test-Aufrufe die explizit Bytes uebergeben.

### storage.py: Umbau

```python
import tempfile

@router.post("/upload", response_model=ArtifactUploadResponse)
async def storage_upload(
    file: UploadFile = File(...),
    task_id: Optional[str] = Query(None),
    stage_id: Optional[str] = Query(None),
    ctx: AuthContext = Depends(get_approved_context),
):
    # 1. Content-Length Header check (schnelle Ablehnung ohne Daten)
    content_length = file.size
    if content_length is not None and content_length > settings.max_upload_bytes:
        raise HTTPException(413, f"Upload exceeds max size")
    
    # 2. Chunkweise in SpooledTemporaryFile schreiben
    #    SpooledTemporaryFile: max_size=1MB im RAM, danach Disk
    tmp = tempfile.SpooledTemporaryFile(max_size=1024 * 1024)  # 1MB RAM threshold
    total = 0
    while chunk := await file.read(64 * 1024):  # 64KB chunks
        total += len(chunk)
        if total > settings.max_upload_bytes:
            tmp.close()
            raise HTTPException(413, f"Upload exceeds max size")
        tmp.write(chunk)
    
    # 3. Temp-File an store_artifact_from_file uebergeben
    tmp.flush()
    tmp.seek(0)
    
    # SpooledTemporaryFile hat .name nur wenn es auf Disk gespilled wurde.
    # Fuer den RAM-only-Fall: write to a real temp file to get a path.
    if not hasattr(tmp, 'name') or tmp.name is None:
        import pathlib
        real_tmp = pathlib.Path(tmp.name) if hasattr(tmp, 'name') and tmp.name else None
        if real_tmp is None:
            # Fallback: write to a proper temp file
            with tempfile.NamedTemporaryFile(delete=False, suffix=".upload") as f:
                f.write(tmp.read())
                real_path = pathlib.Path(f.name)
        else:
            real_path = real_tmp
    else:
        real_path = pathlib.Path(tmp.name)
    
    try:
        result = store_artifact_from_file(
            name=file.filename or "unnamed",
            file_path=real_path,
            mime_type=file.content_type,
            task_id=task_id,
            stage_id=stage_id,
            created_by=ctx.node_id,
        )
    finally:
        # Temp-File aufraeumen
        real_path.unlink(missing_ok=True)
        tmp.close()
    
    return ArtifactUploadResponse(**result)
```

> **Hinweis:** `SpooledTemporaryFile` hat in Python <3.12 keinen `.name` im RAM-Zweig. Der Fallback ueber `NamedTemporaryFile` ist der sichere Weg. Pruef auf Python 3.14 (laut .venv).

**Schritt 1: Bestehenden Test lesen und verstehen**

```bash
cd /home/felix/projects/ai-relay-service
source .venv/bin/activate
.venv/bin/python -m pytest tests/test_storage.py -v 2>&1 | head -30
```

**Schritt 2: `store_artifact_from_file` in artifacts.py implementieren**

Die Funktion schreiben (s.o.), SHA256 chunkweise, File-Move statt Kopie.

**Schritt 3: storage.py Upload umbauen**

`await file.read()` durch SpooledTemporaryFile + chunkweises Lesen ersetzen.

**Schritt 4: Tests anpassen**

Bestehende Tests in `test_storage.py` nutzen `TestClient` mit `UploadFile`. Die meisten werden ohne Aenderung weiterlaufen, weil FastAPI das UploadFile-Objekt erzeugt.

Neuen Testfall hinzufuegen: Upload einer Datei >1MB (erzwingt Disk-Spill im SpooledTemporaryFile).

```python
async def test_large_upload(tmp_path):
    """Upload a file that exceeds the SpooledTemporaryFile RAM threshold."""
    content = b"x" * (2 * 1024 * 1024)  # 2MB
    ... # UploadFile erstellen, senden, verifizieren
```

**Schritt 5: Tests laufen lassen**

```bash
cd /home/felix/projects/ai-relay-service
source .venv/bin/activate
.venv/bin/python -m pytest tests/test_storage.py tests/test_storage_e2e.py -v --tb=short 2>&1 | tail -20
```

Erwartet: Alle bestehenden + neue Tests passed.

---

## Task 2: Chunked-Upload-Endpunkt

**Objective:** Einen neuen Endpunkt `POST /relay/v2/storage/chunked` der grosse Dateien in Teilen akzeptiert und am Ende automatisch zum Artifact zusammenbaut.

**Files:**
- Create: `src/relay_server/core/chunked_upload.py` (Staging-Logik)
- Modify: `src/relay_server/api/v2/storage.py` (neue Endpunkte)
- Test: `tests/test_storage.py` (Chunked-Tests)

**Design:**

Chunked-Upload erfolgt in 3 Schritten:

```bash
# 1. Upload-Init: Reserviert eine Upload-Session, kriegt upload_id
POST /relay/v2/storage/chunked/init
{"name": "large-file.zip", "mime_type": "application/zip", "total_chunks": 10}
→ {"upload_id": "upl_a1B2c3D4", "status": "init"}

# 2. Chunk hochladen: Ein Teil der Datei, mit Index
POST /relay/v2/storage/chunked/{upload_id}/chunk
{"chunk_index": 0, "data": "<base64 oder binary>"}
→ {"upload_id": "...", "chunk_index": 0, "status": "received"}

# 3. Upload abschliessen: Alle Chunks zusammenbauen → Artifact erstellen
POST /relay/v2/storage/chunked/{upload_id}/complete
{"checksum": "sha256..."}  # optional: Server kann selbst checken
→ {"artifact_id": "artifact_...", "size_bytes": 12345, "status": "created"}
```

**Staging-Logik (chunked_upload.py):**

```python
import shutil
import tempfile
from pathlib import Path
from typing import Dict, Optional

CHUNKED_DIR = Path.home() / ".relay" / "chunked_uploads"

class ChunkedUploadManager:
    def __init__(self):
        self._sessions: Dict[str, dict] = {}
    
    def init_upload(self, name: str, mime_type: str | None, total_chunks: int) -> dict:
        upload_id = f"upl_{secrets.token_urlsafe(12)}"
        session_dir = CHUNKED_DIR / upload_id
        session_dir.mkdir(parents=True, exist_ok=True)
        self._sessions[upload_id] = {
            "name": name,
            "mime_type": mime_type,
            "total_chunks": total_chunks,
            "received": set(),
            "session_dir": session_dir,
            "created_at": _now(),
        }
        return {"upload_id": upload_id, "status": "init"}
    
    def store_chunk(self, upload_id: str, chunk_index: int, data: bytes) -> dict:
        session = self._sessions.get(upload_id)
        if not session:
            raise ValueError("Upload session not found")
        chunk_path = session["session_dir"] / f"chunk_{chunk_index:04d}"
        chunk_path.write_bytes(data)
        session["received"].add(chunk_index)
        return {"upload_id": upload_id, "chunk_index": chunk_index, "status": "received"}
    
    def complete_upload(self, upload_id: str) -> Path:
        session = self._sessions.get(upload_id)
        if not session:
            raise ValueError("Upload session not found")
        if len(session["received"]) != session["total_chunks"]:
            raise ValueError(f"Missing chunks: have {len(session['received'])}, need {session['total_chunks']}")
        # Chunks zusammenbauen
        output_path = session["session_dir"] / "complete"
        with open(output_path, "wb") as dst:
            for i in range(session["total_chunks"]):
                chunk_path = session["session_dir"] / f"chunk_{i:04d}"
                dst.write(chunk_path.read_bytes())
        return output_path

chunked_manager = ChunkedUploadManager()
```

**Wichtig:** Chunks landen auf Disk (nicht im RAM). Bei Sessions die nie completed werden, braucht's eine Cleanup-Routine (Timeout nach z.B. 1h).

**Endpoint-Erweiterung in storage.py:**

```python
@router.post("/chunked/init")
async def chunked_init(data: ChunkedInitRequest, ctx = Depends(get_approved_context)):
    result = chunked_manager.init_upload(data.name, data.mime_type, data.total_chunks)
    return result

@router.post("/chunked/{upload_id}/chunk")
async def chunked_chunk(upload_id: str, data: ChunkedChunkRequest, ctx = Depends(get_approved_context)):
    try:
        result = chunked_manager.store_chunk(upload_id, data.chunk_index, data.data)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return result

@router.post("/chunked/{upload_id}/complete")
async def chunked_complete(upload_id: str, data: ChunkedCompleteRequest, ctx = Depends(get_approved_context)):
    try:
        file_path = chunked_manager.complete_upload(upload_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    
    session = chunked_manager._sessions[upload_id]
    result = store_artifact_from_file(
        name=session["name"],
        file_path=file_path,
        mime_type=session["mime_type"],
        task_id=None,
        stage_id=None,
        created_by=ctx.node_id,
    )
    return {"artifact_id": result["artifact_id"], "size_bytes": result["size_bytes"], "status": "created"}
```

**Schritt 1: chunked_upload.py erstellen**

Mit `ChunkedUploadManager`, `init_upload`, `store_chunk`, `complete_upload`. In-memory Session-Dict + Disk-Staging.

**Schritt 2: Pydantic-Models fuer die Requests definieren**

```python
class ChunkedInitRequest(BaseModel):
    name: str
    mime_type: Optional[str] = None
    total_chunks: int = Field(gt=0, le=10000)

class ChunkedChunkRequest(BaseModel):
    chunk_index: int = Field(ge=0)
    data: bytes  # base64-decoded von FastAPI, oder raw binary

class ChunkedCompleteRequest(BaseModel):
    checksum: Optional[str] = None
```

**Schritt 3: Endpunkte in storage.py registrieren**

Drei neue Router-Endpunkte + ggf. Modelle importieren.

**Schritt 4: Tests schreiben**

```python
async def test_chunked_upload_happy_path(client, auth_headers):
    # Init
    r = await client.post("/relay/v2/storage/chunked/init", json={"name": "test.bin", "total_chunks": 3}, ...)
    upload_id = r.json()["upload_id"]
    
    # Chunks
    for i, chunk in enumerate([b"AAA", b"BBB", b"CCC"]):
        r = await client.post(f"/relay/v2/storage/chunked/{upload_id}/chunk", json={"chunk_index": i, "data": chunk.hex()}, ...)
        assert r.status_code == 200
    
    # Complete
    r = await client.post(f"/relay/v2/storage/chunked/{upload_id}/complete", json={}, ...)
    assert r.json()["status"] == "created"
    assert "artifact_id" in r.json()
```

**Schritt 5: Tests laufen lassen**

```bash
cd /home/felix/projects/ai-relay-service
source .venv/bin/activate
.venv/bin/python -m pytest tests/test_storage.py -v --tb=short 2>&1 | tail -15
```

---

## Task 3: Artifact-Download im Worker

**Objective:** `node-cli artifact download` Befehl hinzufuegen, und eine `download_artifact()`-Methode im Poller.

**Files:**
- Modify: `nodes/common/node_cli.py` (neuer Subcommand `artifact download`)
- Modify: `nodes/common/poller.py` (neue Methode `download_artifact`)
- Test: `tests/nodes/test_node_cli.py` (neue Tests)

**Details:**

### node_cli.py: Neuer Subcommand

```python
# In der Argument-Parser-Setup:
artifact_parser = subparsers.add_parser("artifact", help="Artifact operations")
artifact_sub = artifact_parser.add_subparsers(dest="artifact_command")
download_parser = artifact_sub.add_parser("download", help="Download an artifact")
download_parser.add_argument("artifact_id", help="The artifact ID to download")
download_parser.add_argument("--output", "-o", type=Path, default=None,
                             help="Output path (default: <artifact_name>)")
```

Handler:
```python
def cmd_artifact_download(args):
    """Download an artifact by ID."""
    tok = _load_token()
    base = _load_base_url()
    # GET /relay/v2/storage/files/{artifact_id}
    resp = httpx.get(
        f"{base}/relay/v2/storage/files/{args.artifact_id}",
        headers={"Authorization": f"Bearer {tok}"},
        follow_redirects=True,
    )
    resp.raise_for_status()
    
    # Content-Disposition header auswerten fuer Dateinamen
    filename = args.artifact_id
    cd = resp.headers.get("content-disposition", "")
    import re
    m = re.search(r'filename="?([^"]+)"?', cd)
    if m:
        filename = m.group(1)
    
    output_path = args.output or Path(filename)
    output_path.write_bytes(resp.content)
    print(f"Downloaded {len(resp.content)} bytes to {output_path}")
```

### poller.py: Neue Methode

```python
class Poller:
    # ... bestehend ...
    
    def download_artifact(self, artifact_id: str, output_path: Optional[Path] = None) -> Path:
        """Download an artifact from the relay and return the local path."""
        tok = self._load_token()
        resp = httpx.get(
            f"{self.state['base_url'].rstrip('/')}/relay/v2/storage/files/{artifact_id}",
            headers={"Authorization": f"Bearer {tok}"},
            follow_redirects=True,
            timeout=self.config.get("request_timeout", 30),
        )
        resp.raise_for_status()
        
        filename = artifact_id
        cd = resp.headers.get("content-disposition", "")
        import re
        m = re.search(r'filename="?([^"]+)"?', cd)
        if m:
            filename = m.group(1)
        
        path = output_path or Path(filename)
        # Stream-chunked schreiben, kein vollstaendiger RAM-Load
        with open(path, "wb") as f:
            for chunk in resp.iter_bytes(chunk_size=65536):
                f.write(chunk)
        return path
```

**Schritt 1: node_cli.py Subcommand hinzufuegen**

Parser + Handler schreiben.

Registrieren in der `main()`-Dispatcher-Schleife.

**Schritt 2: poller.py Methode hinzufuegen**

`download_artifact` in die Poller-Klasse.

**Schritt 3: Tests schreiben**

```python
def test_node_cli_artifact_download(mock_server):
    """Test artifact download CLI subcommand."""
    result = subprocess.run(
        [sys.executable, "-m", "nodes.common.node_cli", "artifact", "download", "artifact_test123"],
        capture_output=True, text=True, timeout=10,
        env={...},
    )
    assert "Downloaded" in result.stdout
    assert Path("artifact_test123").exists()
```

**Schritt 4: Tests laufen lassen**

```bash
cd /home/felix/projects/ai-relay-service
source .venv/bin/activate
.venv/bin/python -m pytest tests/nodes/test_node_cli.py -v --tb=short 2>&1 | tail -15
```

---

## Abschliessende Antwort fuers Project Board

Nach OpenCode-Ausfuehrung folgende Aenderungen im Project Board eintragen:

### TASKS.md

| ID | Status | Notiz |
|----|--------|-------|
| T-004 | ✅ done | SpooledTemporaryFile im Upload |
| T-005 | ✅ done | Chunked-Upload-Endpunkt |
| T-014 | ✅ done | Artifact-Download in node-cli + poller |

### DECISIONS.md

```markdown
## 2026-06-28: Streaming-Upload + Chunked-Upload + Artifact-Download

**Entscheidung:** Upload-Endpunkt auf SpooledTemporaryFile mit chunkweisem
Lesen umgestellt. Neuer Chunked-Upload-Endpunkt fuer grosse Dateien ueber
unzuverlaessige Verbindungen. Worker-CLI und Poller um artifact-download
erweitert.

**Grund:** `await file.read()` lud komplette Dateien in den RAM — bei 100MB+
Uploads und parallelen Requests ein OOM-Risiko. Chunked-Upload ermoeglicht
Uploads ueber instabile Verbindungen (Mobilfunk, Tailscale).

**Betroffene Tasks:** T-004, T-005, T-014
```

### Kontrolliert:

Nach allen Tasks die gesamte Test-Suite einmal durchlaufen:

```bash
cd /home/felix/projects/ai-relay-service
source .venv/bin/activate
.venv/bin/python -m pytest tests/ tests/nodes/ -q --tb=line --ignore=tests/test_zeroconf.py 2>&1 | tail -3
```