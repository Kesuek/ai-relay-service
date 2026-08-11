"""Tests for the storage node handlers (T-127).

Exercises each handler script in ``docker/nodes/storage/handlers/`` via
:func:`run_handler` so they run through the same subprocess + JSON
contract as the daemon. The storage base is pointed at a tmp dir via
``RELAY_STORAGE_PATH`` so no real NAS is touched.

Coverage:
* store (data_base64 + artifact_id modes)
* fetch, delete, list, quota, stat, move
* _safe_path: rejects ``../`` traversal and symlink escapes
"""

from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

import pytest

from nodes.common.handler_runner import run_handler

HANDLERS = Path(__file__).resolve().parents[2] / "docker" / "nodes" / "storage" / "handlers"


def _stage(payload=None):
    return {
        "stage_id": "st1",
        "task_id": "tk1",
        "capability": "storage.store",
        "payload": payload or {},
    }


def _ctx(storage_path: Path, **extra) -> dict:
    env = {
        "RELAY_NODE_ID": "node-abc",
        "RELAY_BASE_URL": "http://relay.test",
        "RELAY_TOKEN_FILE": str(storage_path / "token"),
    }
    env.update(extra)
    return env


def _err_text(result: dict) -> str:
    """Extract the handler's error message text from a run_handler result.

    On non-zero exit run_handler returns ``{"error": "handler exited with
    code N", "stdout": "<json>"}`` where ``stdout`` carries the handler's
    own ``{"error": "..."}`` message. On a clean exit-0 failure (exit 0
    with an error dict, or a non-error result) the message is in
    ``result["error"]``. We normalise both so the assertions can target
    the handler's intended message.
    """
    if result.get("error", "").startswith("handler exited"):
        stdout = result.get("stdout", "")
        try:
            parsed = json.loads(stdout)
            return parsed.get("error", stdout)
        except (json.JSONDecodeError, TypeError):
            return stdout or result["error"]
    return result.get("error", "")


def _run(handler_name: str, payload: dict, storage_path: Path, **env) -> dict:
    handler = f"{sys.executable} {HANDLERS / handler_name}"
    ctx = _ctx(storage_path)
    # handler_runner only overlays HANDLER_ENV_KEYS from the context; any
    # extra env vars the test wants to set must land in os.environ so the
    # subprocess inherits them directly.
    old = os.environ.get("RELAY_STORAGE_PATH")
    os.environ["RELAY_STORAGE_PATH"] = str(storage_path)
    prev_extras = {k: os.environ.get(k) for k in env}
    os.environ.update({k: str(v) for k, v in env.items()})
    try:
        return run_handler(handler, _stage(payload), context=ctx, timeout=30)
    finally:
        if old is None:
            os.environ.pop("RELAY_STORAGE_PATH", None)
        else:
            os.environ["RELAY_STORAGE_PATH"] = old
        for k, v in prev_extras.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ---------------------------------------------------------------------------
# _safe_path
# ---------------------------------------------------------------------------


class TestSafePath:
    def test_traversal_rejected(self, tmp_path: Path):
        result = _run("store.py", {"path": "../../etc/passwd", "data_base64": "AAA="}, tmp_path)
        assert result.get("error"), result
        assert "traversal" in _err_text(result).lower()

    def test_absolute_escape_rejected(self, tmp_path: Path):
        result = _run("store.py", {"path": "/etc/passwd", "data_base64": "AAA="}, tmp_path)
        assert "traversal" in _err_text(result).lower()

    def test_symlink_escape_rejected(self, tmp_path: Path):
        # Create a symlink inside storage pointing outside the tree.
        outside = tmp_path.parent / "outside-target"
        outside.mkdir(exist_ok=True)
        link = tmp_path / "escape"
        try:
            link.symlink_to(outside)
        except OSError:
            pytest.skip("cannot create symlink on this platform")
        result = _run("store.py", {"path": "escape/evil.txt", "data_base64": "AAA="}, tmp_path)
        assert "traversal" in _err_text(result).lower()

    def test_legitimate_subpath_allowed(self, tmp_path: Path):
        result = _run("store.py", {"path": "sub/dir/file.txt", "data_base64": "aGVsbG8="}, tmp_path)
        assert result.get("status") == "stored", result
        assert (tmp_path / "sub" / "dir" / "file.txt").read_text() == "hello"


# ---------------------------------------------------------------------------
# store
# ---------------------------------------------------------------------------


class TestStore:
    def test_store_data_base64(self, tmp_path: Path):
        data = b"hello storage"
        result = _run(
            "store.py",
            {"path": "a/b/c.bin", "data_base64": base64.b64encode(data).decode()},
            tmp_path,
        )
        assert result["status"] == "stored"
        assert result["size_bytes"] == len(data)
        assert result["path"] == "a/b/c.bin"
        assert (tmp_path / "a" / "b" / "c.bin").read_bytes() == data

    def test_store_overwrites_existing(self, tmp_path: Path):
        (tmp_path / "f.txt").write_text("old")
        result = _run(
            "store.py",
            {"path": "f.txt", "data_base64": base64.b64encode(b"new").decode()},
            tmp_path,
        )
        assert result["status"] == "stored"
        assert (tmp_path / "f.txt").read_text() == "new"

    def test_store_missing_payload_field(self, tmp_path: Path):
        result = _run("store.py", {"path": "f.txt"}, tmp_path)
        assert "data_base64 or artifact_id" in _err_text(result).lower()

    def test_store_invalid_base64(self, tmp_path: Path):
        result = _run("store.py", {"path": "f.txt", "data_base64": "not-base64!!"}, tmp_path)
        assert "invalid data_base64" in _err_text(result).lower()


# ---------------------------------------------------------------------------
# fetch
# ---------------------------------------------------------------------------


class TestFetch:
    def test_fetch_returns_base64(self, tmp_path: Path):
        (tmp_path / "x.bin").write_bytes(b"fetch me")
        result = _run("fetch.py", {"path": "x.bin"}, tmp_path)
        assert result["status"] == "fetched"
        assert result["size_bytes"] == 8
        assert base64.b64decode(result["data_base64"]) == b"fetch me"
        assert result["path"] == "x.bin"

    def test_fetch_missing_file(self, tmp_path: Path):
        result = _run("fetch.py", {"path": "nope.bin"}, tmp_path)
        assert _err_text(result) == "not found"


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


class TestDelete:
    def test_delete_file(self, tmp_path: Path):
        (tmp_path / "rm.txt").write_text("x")
        result = _run("delete.py", {"path": "rm.txt"}, tmp_path)
        assert result["status"] == "deleted"
        assert not (tmp_path / "rm.txt").exists()

    def test_delete_directory_recursive(self, tmp_path: Path):
        d = tmp_path / "tree"
        d.mkdir()
        (d / "a.txt").write_text("a")
        (d / "sub").mkdir()
        (d / "sub" / "b.txt").write_text("b")
        result = _run("delete.py", {"path": "tree"}, tmp_path)
        assert result["status"] == "deleted"
        assert not d.exists()

    def test_delete_not_found(self, tmp_path: Path):
        result = _run("delete.py", {"path": "missing"}, tmp_path)
        assert result["status"] == "not_found"


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


class TestList:
    def test_list_empty(self, tmp_path: Path):
        result = _run("list.py", {"prefix": ""}, tmp_path)
        assert result["status"] == "listed"
        assert result["count"] == 0
        assert result["files"] == []

    def test_list_lists_files(self, tmp_path: Path):
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.txt").write_text("bb")
        result = _run("list.py", {"prefix": ""}, tmp_path)
        paths = {f["path"] for f in result["files"]}
        assert "a.txt" in paths
        assert "sub/b.txt" in paths
        # size_bytes correct.
        b = next(f for f in result["files"] if f["path"] == "sub/b.txt")
        assert b["size_bytes"] == 2

    def test_list_with_prefix(self, tmp_path: Path):
        (tmp_path / "keep.txt").write_text("k")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "in.txt").write_text("i")
        (tmp_path / "out.txt").write_text("o")
        result = _run("list.py", {"prefix": "sub"}, tmp_path)
        paths = {f["path"] for f in result["files"]}
        assert paths == {"sub/in.txt"}

    def test_list_prefix_traversal_rejected(self, tmp_path: Path):
        result = _run("list.py", {"prefix": "../"}, tmp_path)
        assert "traversal" in _err_text(result).lower()


# ---------------------------------------------------------------------------
# quota
# ---------------------------------------------------------------------------


class TestQuota:
    def test_quota_returns_fields(self, tmp_path: Path):
        result = _run("quota.py", {}, tmp_path)
        assert result["status"] == "quota"
        for k in (
            "total_bytes",
            "used_bytes",
            "free_bytes",
            "usage_ratio",
            "threshold",
            "threshold_exceeded",
        ):
            assert k in result
        assert 0.0 <= result["usage_ratio"] <= 1.0
        assert result["threshold_exceeded"] == (result["usage_ratio"] >= result["threshold"])

    def test_quota_threshold_from_env(self, tmp_path: Path):
        # Force a threshold of 0.0 so threshold_exceeded is always True.
        result = _run("quota.py", {}, tmp_path, RELAY_STORAGE_QUOTA_THRESHOLD="0.0")
        assert result["threshold"] == 0.0
        assert result["threshold_exceeded"] is True


# ---------------------------------------------------------------------------
# stat
# ---------------------------------------------------------------------------


class TestStat:
    def test_stat_file(self, tmp_path: Path):
        (tmp_path / "s.txt").write_text("hello")
        result = _run("stat.py", {"path": "s.txt"}, tmp_path)
        assert result["status"] == "stat"
        assert result["size_bytes"] == 5
        assert result["is_dir"] is False
        assert result["path"] == "s.txt"

    def test_stat_directory(self, tmp_path: Path):
        (tmp_path / "d").mkdir()
        result = _run("stat.py", {"path": "d"}, tmp_path)
        assert result["status"] == "stat"
        assert result["is_dir"] is True

    def test_stat_missing(self, tmp_path: Path):
        result = _run("stat.py", {"path": "nope"}, tmp_path)
        assert _err_text(result) == "not found"


# ---------------------------------------------------------------------------
# move
# ---------------------------------------------------------------------------


class TestMove:
    def test_move_file(self, tmp_path: Path):
        (tmp_path / "src.txt").write_text("content")
        result = _run("move.py", {"from": "src.txt", "to": "dst.txt"}, tmp_path)
        assert result["status"] == "moved"
        assert not (tmp_path / "src.txt").exists()
        assert (tmp_path / "dst.txt").read_text() == "content"

    def test_move_creates_parent_dirs(self, tmp_path: Path):
        (tmp_path / "x.txt").write_text("c")
        result = _run("move.py", {"from": "x.txt", "to": "deep/nested/y.txt"}, tmp_path)
        assert result["status"] == "moved"
        assert (tmp_path / "deep" / "nested" / "y.txt").read_text() == "c"

    def test_move_source_missing(self, tmp_path: Path):
        result = _run("move.py", {"from": "nope", "to": "y.txt"}, tmp_path)
        assert _err_text(result) == "source not found"

    def test_move_traversal_rejected(self, tmp_path: Path):
        result = _run("move.py", {"from": "../x", "to": "y"}, tmp_path)
        assert "traversal" in _err_text(result).lower()


# ---------------------------------------------------------------------------
# T-133: store with action extract / store_as_is (tar.gz)
# ---------------------------------------------------------------------------


def _make_tar_gz(files: dict[str, bytes]) -> bytes:
    """Build an in-memory tar.gz from {relpath: bytes}."""
    import io
    import tarfile

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for rel, data in files.items():
            info = tarfile.TarInfo(rel)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class TestStoreTarGz:
    def test_store_as_is_keeps_archive(self, tmp_path: Path):
        tgz = _make_tar_gz({"a.txt": b"hello", "sub/b.txt": b"world"})
        result = _run(
            "store.py",
            {"path": "bundle.tar.gz", "action": "store_as_is", "data_base64": base64.b64encode(tgz).decode()},
            tmp_path,
        )
        assert result["status"] == "stored", result
        # archive kept as-is, not extracted
        assert (tmp_path / "bundle.tar.gz").is_file()
        assert not (tmp_path / "a.txt").exists()

    def test_store_extract_unpacks(self, tmp_path: Path):
        tgz = _make_tar_gz({"a.txt": b"hello", "sub/b.txt": b"world"})
        result = _run(
            "store.py",
            {"path": "bundle", "action": "extract", "data_base64": base64.b64encode(tgz).decode()},
            tmp_path,
        )
        assert result["status"] == "stored", result
        assert (tmp_path / "bundle" / "a.txt").read_bytes() == b"hello"
        assert (tmp_path / "bundle" / "sub" / "b.txt").read_bytes() == b"world"
        # no leftover archive
        assert not (tmp_path / "bundle.tar.gz").exists()

    def test_store_extract_traversal_in_archive_rejected(self, tmp_path: Path):
        # a tar entry escaping the target dir must be rejected
        import io
        import tarfile

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            info = tarfile.TarInfo("../evil.txt")
            info.size = 4
            tf.addfile(info, io.BytesIO(b"evil"))
        result = _run(
            "store.py",
            {"path": "bundle", "action": "extract", "data_base64": base64.b64encode(buf.getvalue()).decode()},
            tmp_path,
        )
        assert result.get("error"), result
        assert not (tmp_path.parent / "evil.txt").exists()


# ---------------------------------------------------------------------------
# T-135: storage.extract / storage.archive
# ---------------------------------------------------------------------------


class TestExtract:
    def test_extract_unpacks_archive(self, tmp_path: Path):
        tgz = _make_tar_gz({"a.txt": b"hello", "sub/b.txt": b"world"})
        (tmp_path / "bundle.tar.gz").write_bytes(tgz)
        result = _run("extract.py", {"path": "bundle.tar.gz"}, tmp_path)
        assert result["status"] == "extracted", result
        assert (tmp_path / "bundle" / "a.txt").read_bytes() == b"hello"
        assert (tmp_path / "bundle" / "sub" / "b.txt").read_bytes() == b"world"

    def test_extract_missing(self, tmp_path: Path):
        result = _run("extract.py", {"path": "nope.tar.gz"}, tmp_path)
        assert "not found" in _err_text(result).lower()

    def test_extract_traversal_rejected(self, tmp_path: Path):
        result = _run("extract.py", {"path": "../x.tar.gz"}, tmp_path)
        assert "traversal" in _err_text(result).lower()


class TestArchive:
    def test_archive_packs_directory(self, tmp_path: Path):
        d = tmp_path / "proj"
        d.mkdir()
        (d / "a.txt").write_text("hello")
        (d / "sub").mkdir()
        (d / "sub" / "b.txt").write_text("world")
        result = _run("archive.py", {"path": "proj", "target": "proj.tar.gz"}, tmp_path)
        assert result["status"] == "archived", result
        assert (tmp_path / "proj.tar.gz").is_file()
        # verify contents
        import io
        import tarfile

        with tarfile.open(fileobj=io.BytesIO((tmp_path / "proj.tar.gz").read_bytes()), mode="r:gz") as tf:
            names = tf.getnames()
        assert "proj/a.txt" in names
        assert "proj/sub/b.txt" in names

    def test_archive_missing_source(self, tmp_path: Path):
        result = _run("archive.py", {"path": "nope", "target": "nope.tar.gz"}, tmp_path)
        assert "not found" in _err_text(result).lower()

    def test_archive_traversal_rejected(self, tmp_path: Path):
        result = _run("archive.py", {"path": "../x", "target": "x.tar.gz"}, tmp_path)
        assert "traversal" in _err_text(result).lower()
