"""Tests for nodes.common.node_utils — token persistence (T-088)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nodes.common import node_utils


@pytest.fixture()
def isolated_token_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    base = tmp_path / "relay"
    base.mkdir(parents=True, exist_ok=True)
    token_path = base / "ai-relay-agent.token"
    monkeypatch.setattr(node_utils, "BASE_DIR", base)
    monkeypatch.setattr(node_utils, "TOKEN_PATH", token_path)
    return token_path


def test_save_load_token_json_format(isolated_token_path: Path):
    """save_token persists token + expires_at as a JSON envelope and
    load_token returns the same dict structure."""
    expires = "2026-08-08T08:30:00+00:00"
    node_utils.save_token("rt_abc123", expires_at=expires)

    assert isolated_token_path.exists()
    # File contains valid JSON with the expected fields.
    data = json.loads(isolated_token_path.read_text())
    assert data["token"] == "rt_abc123"
    assert data["expires_at"] == expires

    loaded = node_utils.load_token()
    assert loaded == {"token": "rt_abc123", "expires_at": expires}


def test_save_token_sets_0600_perms(isolated_token_path: Path):
    """save_token writes the token file with restrictive 0600 perms so
    other local users cannot read the runtime token (T-171)."""
    node_utils.save_token("rt_permtest", expires_at=None)
    mode = isolated_token_path.stat().st_mode & 0o777
    assert mode == 0o600, f"expected 0600, got {oct(mode)}"


def test_save_token_without_expires_at(isolated_token_path: Path):
    """expires_at defaults to None when omitted."""
    node_utils.save_token("rt_only")
    loaded = node_utils.load_token()
    assert loaded == {"token": "rt_only", "expires_at": None}
    assert json.loads(isolated_token_path.read_text())["expires_at"] is None


def test_load_token_legacy_plaintext(isolated_token_path: Path):
    """A legacy plaintext token (pre-T-088) is detected and returned
    with expires_at=None so existing installs keep working until the
    next save_token() migrates the file to JSON."""
    isolated_token_path.write_text("rt_legacy_token\n", encoding="utf-8")
    loaded = node_utils.load_token()
    assert loaded == {"token": "rt_legacy_token", "expires_at": None}


def test_load_token_missing_file(isolated_token_path: Path):
    """load_token returns None when no token file exists."""
    assert not isolated_token_path.exists()
    assert node_utils.load_token() is None


def test_load_token_empty_file(isolated_token_path: Path):
    """An empty token file is treated as no token."""
    isolated_token_path.write_text("", encoding="utf-8")
    assert node_utils.load_token() is None


def test_save_token_is_atomic(isolated_token_path: Path):
    """save_token writes via a tmp file + rename; no .tmp leftover."""
    node_utils.save_token("rt_atomic", expires_at="2026-08-08T08:30:00+00:00")
    assert isolated_token_path.exists()
    assert not (isolated_token_path.parent / (isolated_token_path.name + ".tmp")).exists()


def test_load_token_corrupted_json_falls_back_to_plaintext(
    isolated_token_path: Path,
):
    """If the token file starts with ``{`` but isn't valid JSON, we fall
    back to treating the whole content as the token rather than crashing."""
    isolated_token_path.write_text("{not valid json\n", encoding="utf-8")
    loaded = node_utils.load_token()
    assert loaded == {"token": "{not valid json", "expires_at": None}


def test_legacy_token_migrates_on_next_save(isolated_token_path: Path):
    """A legacy plaintext token is read with expires_at=None and, after
    a subsequent save_token() call, the file is in the JSON format."""
    isolated_token_path.write_text("rt_legacy\n", encoding="utf-8")
    assert node_utils.load_token() == {"token": "rt_legacy", "expires_at": None}

    node_utils.save_token("rt_legacy", expires_at="2026-09-01T00:00:00+00:00")
    raw = isolated_token_path.read_text()
    assert raw.lstrip().startswith("{")
    assert json.loads(raw) == {"token": "rt_legacy", "expires_at": "2026-09-01T00:00:00+00:00"}