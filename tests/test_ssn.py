"""Tests for the Server-Side Node (SSN) capability-pages handler (T-069).

Covers the four actions exposed by ``nodes/handlers/ssn-capability-pages.sh``:
``add``/``update`` (download artifact → store as <capability>.html),
``delete`` (remove the page) and ``list`` (enumerate managed pages).

The handler is a shell script driven by a JSON payload on stdin. The
``add``/``update`` path invokes ``node-cli artifact download``; we
substitute a mock downloader via the ``NODE_CLI_DOWNLOAD`` env var so the
tests never touch the relay.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

HANDLER = Path(__file__).resolve().parents[1] / "nodes" / "handlers" / "ssn-capability-pages.sh"


def _run_handler(payload: dict, *, home: Path, download_mock: str | None = None) -> tuple[int, str, str]:
    """Run the SSN handler with the given payload and return (rc, stdout, stderr)."""
    env = dict(os.environ)
    env["HOME"] = str(home)
    # Keep PATH so python3/stat are found; drop the real relay repo from
    # PYTHONPATH so an accidental real node-cli call would not pick up
    # ~/.relay credentials.
    if download_mock is not None:
        env["NODE_CLI_DOWNLOAD"] = download_mock
    proc = subprocess.run(  # noqa: S603 — handler is a trusted repo file
        ["bash", str(HANDLER)],
        input=json.dumps(payload).encode(),
        capture_output=True,
        env=env,
        timeout=20,
    )
    return proc.returncode, proc.stdout.decode(), proc.stderr.decode()


@pytest.fixture
def ssn_home(tmp_path, monkeypatch) -> Path:
    """Isolated HOME so ~/.ssn/pages does not leak into the real home."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return home


def _mock_downloader(tmp_path: Path) -> str:
    """Write a small shell mock that copies a fixed HTML to --output and return its invocation."""
    mock = tmp_path / "mock-download.sh"
    mock.write_text(textwrap.dedent("""\
        #!/usr/bin/env bash
        # mock: <args...> --output <path>
        out=""
        while [ $# -gt 0 ]; do
          case "$1" in
            --output|-o) out="$2"; shift 2 ;;
            *) shift ;;
          esac
        done
        printf '<html><body>mock page</body></html>' > "$out"
    """))
    mock.chmod(0o755)
    return f"{mock} artifact download"


# ---------------------------------------------------------------------------
# add / update
# ---------------------------------------------------------------------------


def test_ssn_handler_add_creates_html_file(ssn_home, tmp_path):
    rc, out, err = _run_handler(
        {"action": "add", "capability": "image.generate.mflux", "artifact_id": "artifact_abc"},
        home=ssn_home,
        download_mock=_mock_downloader(tmp_path),
    )
    assert rc == 0, err
    result = json.loads(out)
    assert result["status"] == "ok"
    assert result["action"] == "add"
    assert result["capability"] == "image.generate.mflux"
    assert result["size_bytes"] > 0

    page = ssn_home / ".ssn" / "pages" / "image.generate.mflux.html"
    assert page.is_file()
    assert page.read_bytes() == b"<html><body>mock page</body></html>"


def test_ssn_handler_update_overwrites_existing_page(ssn_home, tmp_path):
    page = ssn_home / ".ssn" / "pages" / "image.generate.mflux.html"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_bytes(b"<old/>")

    rc, out, err = _run_handler(
        {"action": "update", "capability": "image.generate.mflux", "artifact_id": "artifact_def"},
        home=ssn_home,
        download_mock=_mock_downloader(tmp_path),
    )
    assert rc == 0, err
    result = json.loads(out)
    assert result["action"] == "update"
    assert page.read_bytes() == b"<html><body>mock page</body></html>"


def test_ssn_handler_add_requires_capability_and_artifact_id(ssn_home):
    rc, out, err = _run_handler({"action": "add", "capability": "x"}, home=ssn_home)
    assert rc != 0
    assert "capability" in err or "artifact_id" in err


def test_ssn_handler_add_rejects_path_traversal(ssn_home):
    rc, out, err = _run_handler(
        {"action": "add", "capability": "../escape", "artifact_id": "a"}, home=ssn_home
    )
    assert rc != 0
    assert "path" in err or "traversal" in err


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


def test_ssn_handler_delete_removes_existing_page(ssn_home):
    page = ssn_home / ".ssn" / "pages" / "image.generate.mflux.html"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_bytes(b"<html/>")

    rc, out, err = _run_handler(
        {"action": "delete", "capability": "image.generate.mflux"}, home=ssn_home
    )
    assert rc == 0, err
    result = json.loads(out)
    assert result["status"] == "ok"
    assert result["deleted"] is True
    assert not page.exists()


def test_ssn_handler_delete_missing_page_reports_deleted_false(ssn_home):
    rc, out, err = _run_handler(
        {"action": "delete", "capability": "never.added"}, home=ssn_home
    )
    assert rc == 0, err
    result = json.loads(out)
    assert result["deleted"] is False


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def test_ssn_handler_list_empty(ssn_home):
    rc, out, err = _run_handler({"action": "list"}, home=ssn_home)
    assert rc == 0, err
    result = json.loads(out)
    assert result["capabilities"] == []


def test_ssn_handler_list_returns_capability_names(ssn_home):
    pages = ssn_home / ".ssn" / "pages"
    pages.mkdir(parents=True)
    (pages / "image.generate.mflux.html").write_bytes(b"<x/>")
    (pages / "code.ai.html").write_bytes(b"<y/>")
    # Non-html files must be ignored.
    (pages / "README.txt").write_bytes(b"ignore me")

    rc, out, err = _run_handler({"action": "list"}, home=ssn_home)
    assert rc == 0, err
    result = json.loads(out)
    names = set(result["capabilities"])
    assert names == {"image.generate.mflux", "code.ai"}


# ---------------------------------------------------------------------------
# unknown action
# ---------------------------------------------------------------------------


def test_ssn_handler_unknown_action_fails(ssn_home):
    rc, out, err = _run_handler({"action": "bogus"}, home=ssn_home)
    assert rc != 0
    assert "unknown action" in err


# ---------------------------------------------------------------------------
# Server config: SSN settings exist and are off by default
# ---------------------------------------------------------------------------


def test_ssn_config_defaults():
    from relay_server.config import Settings

    s = Settings()
    assert s.ssn_enabled is False
    assert s.ssn_auto_approve is True
    assert s.ssn_service_unit == "ai-relay-ssn.service"


def test_ssn_config_no_capability_pages_dir():
    """T-069 removed capability_pages_dir — ensure it is gone."""
    from relay_server.config import Settings

    s = Settings()
    assert not hasattr(s, "capability_pages_dir")