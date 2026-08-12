"""Tests for the storage-node bridge server (T-128).

Covers the source-IP allowlist middleware (allow server IP, reject
others with 403, fail-closed when no IP configured) and the upload/
download streaming endpoints. Uses Starlette's TestClient so no uvicorn
is needed.
"""

from __future__ import annotations

# The bridge_server module lives under docker/nodes/storage/ which is not a
# package — add it to sys.path so the import works from the test suite.
import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient

BRIDGE_DIR = Path(__file__).resolve().parents[2] / "docker" / "nodes" / "storage"
sys.path.insert(0, str(BRIDGE_DIR))

from bridge_server import (  # noqa: E402
    _backup_data_path,
    _channel_dir,
    _resolve_server_ip,
    create_app,
)


@pytest.fixture()
def storage_base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    base = tmp_path / "storage"
    base.mkdir()
    monkeypatch.setattr("bridge_server.STORAGE_PATH", base)
    monkeypatch.setattr("bridge_server.CHANNELS_DIR", base / "channels")
    monkeypatch.setattr("bridge_server.BACKUPS_DIR", base / "backups")
    return base


def _client(allowed_ip: str | None, storage_base: Path):
    app = create_app(allowed_ip=allowed_ip)
    return TestClient(app, client=("192.0.2.10", 12345))


# ---------------------------------------------------------------------------
# Source-IP allowlist
# ---------------------------------------------------------------------------


class TestSourceIPAllowlist:
    def test_allowed_ip_passes(self, storage_base: Path):
        client = _client("192.0.2.10", storage_base)
        # POST an upload from the allowed IP — should succeed (200/JSON).
        r = client.post("/upload/ch_1", content=b"hello")
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "stored"

    def test_non_matching_ip_rejected(self, storage_base: Path):
        # TestClient client IP is 192.0.2.10; allowlist a different IP.
        client = _client("10.0.0.99", storage_base)
        r = client.post("/upload/ch_1", content=b"hello")
        assert r.status_code == 403, r.text
        assert "forbidden" in r.json()["error"].lower()

    def test_no_allowed_ip_fails_closed(self, storage_base: Path):
        client = _client(None, storage_base)
        r = client.post("/upload/ch_1", content=b"hello")
        assert r.status_code == 403, r.text
        assert "allowlist" in r.json()["error"].lower()

    def test_get_also_enforced(self, storage_base: Path):
        client = _client("10.0.0.99", storage_base)
        r = client.get("/download/ch_1")
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Upload endpoint
# ---------------------------------------------------------------------------


class TestUploadChannel:
    def test_streams_body_to_disk(self, storage_base: Path):
        client = _client("192.0.2.10", storage_base)
        body = b"x" * 4096
        r = client.post("/upload/ch_big", content=body)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "stored"
        assert data["channel_id"] == "ch_big"
        assert data["size_bytes"] == 4096
        # Without an X-Filename header the file lands as data.bin in the
        # channel dir (T-162).
        assert (storage_base / "channels" / "ch_big" / "data.bin").read_bytes() == body

    def test_preserves_filename_header(self, storage_base: Path):
        client = _client("192.0.2.10", storage_base)
        body = b"tar contents"
        r = client.post(
            "/upload/ch_named", content=body, headers={"X-Filename": "sims4-save.tar.gz"}
        )
        assert r.status_code == 200, r.text
        assert r.json()["filename"] == "sims4-save.tar.gz"
        assert (storage_base / "channels" / "ch_named" / "sims4-save.tar.gz").read_bytes() == body

    def test_filename_traversal_stripped(self, storage_base: Path):
        client = _client("192.0.2.10", storage_base)
        r = client.post(
            "/upload/ch_evil", content=b"x", headers={"X-Filename": "../../etc/passwd"}
        )
        assert r.status_code == 200, r.text
        # The traversal is stripped to the basename; nothing escapes channels/.
        assert r.json()["filename"] == "passwd"
        assert (storage_base / "channels" / "ch_evil" / "passwd").is_file()
        assert not (storage_base / "etc" / "passwd").exists()

    def test_invalid_channel_id_rejected(self, storage_base: Path):
        client = _client("192.0.2.10", storage_base)
        # Starlette normalizes ".."/"." out of the path before the route
        # matches, so these land as 404 (still a rejection — the escape
        # never reaches the handler). The validator is covered below
        # via the direct _channel_dir unit test.
        r = client.post("/upload/..", content=b"bad")
        assert r.status_code in (400, 404)

    def test_empty_body_stored(self, storage_base: Path):
        client = _client("192.0.2.10", storage_base)
        r = client.post("/upload/ch_empty", content=b"")
        assert r.status_code == 200
        assert r.json()["size_bytes"] == 0
        assert (storage_base / "channels" / "ch_empty" / "data.bin").read_bytes() == b""


# ---------------------------------------------------------------------------
# Download endpoint
# ---------------------------------------------------------------------------


class TestDownloadChannel:
    def test_streams_file_back(self, storage_base: Path):
        client = _client("192.0.2.10", storage_base)
        # Upload first (with a filename so the download echoes it).
        client.post(
            "/upload/ch_dl", content=b"download me", headers={"X-Filename": "save.tar.gz"}
        )
        r = client.get("/download/ch_dl")
        assert r.status_code == 200
        assert r.content == b"download me"
        assert r.headers.get("content-length") == str(len(b"download me"))
        assert r.headers.get("x-filename") == "save.tar.gz"

    def test_missing_file_404(self, storage_base: Path):
        client = _client("192.0.2.10", storage_base)
        r = client.get("/download/ch_missing")
        assert r.status_code == 404

    def test_invalid_channel_id_rejected(self, storage_base: Path):
        client = _client("192.0.2.10", storage_base)
        r = client.get("/download/..")
        assert r.status_code in (400, 404)


class TestChannelPathValidator:
    """The _channel_dir guard rejects escapes even when reached directly."""

    def test_rejects_dot(self, storage_base: Path):
        with pytest.raises(ValueError):
            _channel_dir(".")

    def test_rejects_dotdot(self, storage_base: Path):
        with pytest.raises(ValueError):
            _channel_dir("..")

    def test_rejects_slash(self, storage_base: Path):
        with pytest.raises(ValueError):
            _channel_dir("sub/dir")

    def test_rejects_backslash(self, storage_base: Path):
        with pytest.raises(ValueError):
            _channel_dir("sub\\dir")

    def test_rejects_empty(self, storage_base: Path):
        with pytest.raises(ValueError):
            _channel_dir("")

    def test_accepts_plain_id(self, storage_base: Path):
        p = _channel_dir("ch_abc123")
        assert p == storage_base / "channels" / "ch_abc123"
        assert p.parent.exists()


# ---------------------------------------------------------------------------
# Backup bridge endpoints
# ---------------------------------------------------------------------------


class TestUploadBackup:
    def test_streams_body_to_backup_data_bin(self, storage_base: Path):
        client = _client("192.0.2.10", storage_base)
        body = b"x" * 4096
        r = client.post("/backup/bk_abc", content=body)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "stored"
        assert data["backup_id"] == "bk_abc"
        assert data["size_bytes"] == 4096
        assert (storage_base / "backups" / "bk_abc" / "data.bin").read_bytes() == body

    def test_invalid_backup_id_rejected(self, storage_base: Path):
        client = _client("192.0.2.10", storage_base)
        r = client.post("/backup/..", content=b"bad")
        assert r.status_code in (400, 404)


class TestDownloadBackup:
    def test_streams_backup_data_bin_back(self, storage_base: Path):
        client = _client("192.0.2.10", storage_base)
        client.post("/backup/bk_dl", content=b"backup data")
        r = client.get("/backup/bk_dl")
        assert r.status_code == 200
        assert r.content == b"backup data"
        assert r.headers.get("content-length") == str(len(b"backup data"))

    def test_missing_backup_404(self, storage_base: Path):
        client = _client("192.0.2.10", storage_base)
        r = client.get("/backup/bk_missing")
        assert r.status_code == 404


class TestBackupDataPathValidator:
    def test_rejects_traversal(self, storage_base: Path):
        for bad in (".", "..", "a/b", "a\\b"):
            with pytest.raises(ValueError):
                _backup_data_path(bad)

    def test_accepts_plain_id(self, storage_base: Path):
        p = _backup_data_path("bk_abc123")
        assert p == storage_base / "backups" / "bk_abc123" / "data.bin"
        assert (storage_base / "backups").exists()


# ---------------------------------------------------------------------------
# _resolve_server_ip
# ---------------------------------------------------------------------------


class TestResolveServerIP:
    def test_explicit_override(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("RELAY_SERVER_IP", "10.1.2.3")
        monkeypatch.delenv("RELAY_URL", raising=False)
        monkeypatch.delenv("RELAY_BASE_URL", raising=False)
        assert _resolve_server_ip() == "10.1.2.3"

    def test_empty_override_falls_through(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("RELAY_SERVER_IP", "  ")
        monkeypatch.setenv("RELAY_URL", "http://127.0.0.1:8788")
        # An empty RELAY_SERVER_IP falls through to RELAY_URL resolution.
        assert _resolve_server_ip() == "127.0.0.1"

    def test_no_env_returns_none(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("RELAY_SERVER_IP", raising=False)
        monkeypatch.delenv("RELAY_URL", raising=False)
        monkeypatch.delenv("RELAY_BASE_URL", raising=False)
        # mDNS discovery finds nothing on this network → still None.
        monkeypatch.setattr(
            "nodes.common.relay_client._discover_relay_mdns",
            lambda timeout=2.0: None,
        )
        assert _resolve_server_ip() is None

    def test_mdns_fallback_resolves_ip(self, monkeypatch: pytest.MonkeyPatch):
        # T-152: when RELAY_URL is unset, the bridge allowlist falls back to
        # mDNS discovery so an mDNS-only deployment still gets the relay IP.
        monkeypatch.delenv("RELAY_SERVER_IP", raising=False)
        monkeypatch.delenv("RELAY_URL", raising=False)
        monkeypatch.delenv("RELAY_BASE_URL", raising=False)
        monkeypatch.setattr(
            "nodes.common.relay_client._discover_relay_mdns",
            lambda timeout=2.0: "http://192.168.1.50:8788",
        )
        assert _resolve_server_ip() == "192.168.1.50"

    def test_unresolvable_hostname_returns_none(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("RELAY_SERVER_IP", raising=False)
        monkeypatch.setenv("RELAY_URL", "http://nonexistent.invalid.host.example")
        assert _resolve_server_ip() is None
