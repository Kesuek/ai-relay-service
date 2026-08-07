"""Tests for the ``node-cli route`` subcommand (T-136).

Covers register / unregister / list. Each handler calls the matching
``RelayClient`` helper; we mock those helpers so no network is needed and
assert the CLI output + return code. The ``--json`` variants are
checked too.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from nodes.common import node_cli as cli
from nodes.common import node_config as cl
from nodes.common import node_utils
from nodes.common.relay_client import RelayClient

# ---------------------------------------------------------------------------
# Fixtures — mirror test_node_cli.py's isolated_paths so RelayClient sees a
# writable ~/.relay tree without touching the developer's home.
# ---------------------------------------------------------------------------


@pytest.fixture()
def isolated_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    base = tmp_path / "relay"
    profiles_dir = base / "profiles.d"
    active = base / "node.yaml"
    active_name = base / "node.profile"

    monkeypatch.setattr(cl, "BASE_DIR", base)
    monkeypatch.setattr(cl, "PROFILES_DIR", profiles_dir)
    monkeypatch.setattr(cl, "ACTIVE_PATH", active)
    monkeypatch.setattr(cl, "ACTIVE_PROFILE_NAME_PATH", active_name)
    monkeypatch.setattr(cl._active_cache, "path", active)

    monkeypatch.setattr(cli, "BASE_DIR", base)
    monkeypatch.setattr(cli, "PROFILES_DIR", profiles_dir)
    monkeypatch.setattr(cli, "ACTIVE_PATH", active)
    monkeypatch.setattr(cli, "PID_PATH", base / "node-cli.pid")
    monkeypatch.setattr(cli, "LOG_PATH", base / "node-cli.log")
    monkeypatch.setattr(cli, "STATUS_PATH", base / "worker_status.json")

    monkeypatch.setattr(node_utils, "BASE_DIR", base)
    monkeypatch.setattr(node_utils, "CONFIG_PATH", base / "relay_config.json")
    monkeypatch.setattr(node_utils, "META_PATH", base / "ai-relay-agent.json")
    monkeypatch.setattr(node_utils, "TOKEN_PATH", base / "ai-relay-agent.token")
    monkeypatch.setattr(node_utils, "STATUS_PATH", base / "worker_status.json")

    profiles_dir.mkdir(parents=True, exist_ok=True)
    return base


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content + "\n", encoding="utf-8")
    return path


def _wire_client(monkeypatch: pytest.MonkeyPatch, isolated_paths: Path, client: RelayClient):
    """Patch the facade so with_client() hands our prepared client out."""
    monkeypatch.setattr(
        cli, "load_meta", lambda: {"node_id": "n1", "base_url": "http://relay.test"}
    )
    monkeypatch.setattr(
        cli, "_effective_config", lambda: {"base_url": "http://relay.test", "request_timeout": 5}
    )
    monkeypatch.setattr(cli, "RelayClient", lambda meta, cfg: client)


def _make_client(isolated_paths: Path) -> RelayClient:
    _write(
        isolated_paths / "relay_config.json",
        json.dumps({"base_url": "http://relay:8788", "request_timeout": 10}),
    )
    _write(
        isolated_paths / "ai-relay-agent.json",
        json.dumps({"node_id": "n1", "registration_secret": "rs_abc"}),
    )
    _write(isolated_paths / "ai-relay-agent.token", "rt_test")
    meta = node_utils.load_meta()
    cfg = node_utils.load_config()
    return RelayClient(meta, cfg)


# ---------------------------------------------------------------------------
# route register
# ---------------------------------------------------------------------------


class TestRouteRegister:
    def test_register_calls_client_and_prints_text(self, isolated_paths: Path, monkeypatch, capsys):
        client = _make_client(isolated_paths)
        captured: dict = {}

        def fake_register(self, path, method, upstream, *, ttl_seconds, channel_id, description=""):
            captured.update(
                path=path,
                method=method,
                upstream=upstream,
                ttl_seconds=ttl_seconds,
                channel_id=channel_id,
                description=description,
            )
            return {
                "status": "ok",
                "node_id": "n1",
                "path": path,
                "method": method,
                "expires_at": "2026-08-07T18:00:00+00:00",
                "channel_id": channel_id,
            }

        monkeypatch.setattr(RelayClient, "register_temp_route", fake_register)
        _wire_client(monkeypatch, isolated_paths, client)

        rc = cli.main(
            [
                "route",
                "register",
                "--path",
                "/upload/x",
                "--method",
                "POST",
                "--upstream",
                "http://storage:8791/upload/x",
                "--ttl",
                "3600",
                "--channel",
                "ch_x",
                "--description",
                "upload channel",
            ]
        )
        assert rc == 0
        assert captured["path"] == "/upload/x"
        assert captured["method"] == "POST"
        assert captured["upstream"] == "http://storage:8791/upload/x"
        assert captured["ttl_seconds"] == 3600
        assert captured["channel_id"] == "ch_x"
        assert captured["description"] == "upload channel"
        out = capsys.readouterr().out
        assert "registered" in out.lower()
        assert "/upload/x" in out
        assert "ch_x" in out
        assert "2026-08-07T18:00:00+00:00" in out

    def test_register_json_outputs_server_response(self, isolated_paths: Path, monkeypatch, capsys):
        client = _make_client(isolated_paths)

        def fake_register(self, path, method, upstream, *, ttl_seconds, channel_id, description=""):
            return {
                "status": "ok",
                "node_id": "n1",
                "path": path,
                "method": method,
                "expires_at": "2026-08-07T19:00:00+00:00",
                "channel_id": channel_id,
            }

        monkeypatch.setattr(RelayClient, "register_temp_route", fake_register)
        _wire_client(monkeypatch, isolated_paths, client)

        rc = cli.main(
            [
                "--json",
                "route",
                "register",
                "--path",
                "/upload/y",
                "--method",
                "POST",
                "--upstream",
                "http://storage:8791/upload/y",
                "--ttl",
                "60",
                "--channel",
                "ch_y",
            ]
        )
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["path"] == "/upload/y"
        assert data["channel_id"] == "ch_y"
        assert data["status"] == "ok"

    def test_register_returns_nonzero_on_error(self, isolated_paths: Path, monkeypatch, capsys):
        client = _make_client(isolated_paths)

        def boom(self, *a, **k):
            raise httpx.HTTPStatusError("400", request=None, response=None)

        monkeypatch.setattr(RelayClient, "register_temp_route", boom)
        _wire_client(monkeypatch, isolated_paths, client)

        rc = cli.main(
            [
                "route",
                "register",
                "--path",
                "/upload/z",
                "--method",
                "POST",
                "--upstream",
                "http://x",
                "--ttl",
                "60",
                "--channel",
                "ch_z",
            ]
        )
        assert rc == 1
        err = capsys.readouterr().err
        assert "failed to register route" in err.lower()


# ---------------------------------------------------------------------------
# route unregister
# ---------------------------------------------------------------------------


class TestRouteUnregister:
    def test_unregister_calls_client_and_prints_text(
        self, isolated_paths: Path, monkeypatch, capsys
    ):
        client = _make_client(isolated_paths)
        captured: dict = {}

        def fake_unregister(self, path, method="GET"):
            captured.update(path=path, method=method)

        monkeypatch.setattr(RelayClient, "unregister_temp_route", fake_unregister)
        _wire_client(monkeypatch, isolated_paths, client)

        rc = cli.main(
            [
                "route",
                "unregister",
                "--path",
                "/upload/del",
                "--method",
                "POST",
            ]
        )
        assert rc == 0
        assert captured["path"] == "/upload/del"
        assert captured["method"] == "POST"
        out = capsys.readouterr().out
        assert "deleted" in out.lower()
        assert "/upload/del" in out

    def test_unregister_json_output(self, isolated_paths: Path, monkeypatch, capsys):
        client = _make_client(isolated_paths)
        monkeypatch.setattr(
            RelayClient, "unregister_temp_route", lambda self, path, method="GET": None
        )
        _wire_client(monkeypatch, isolated_paths, client)

        rc = cli.main(
            [
                "--json",
                "route",
                "unregister",
                "--path",
                "/upload/gone",
                "--method",
                "POST",
            ]
        )
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["status"] == "deleted"
        assert data["path"] == "/upload/gone"
        assert data["method"] == "POST"

    def test_unregister_returns_nonzero_on_error(self, isolated_paths: Path, monkeypatch, capsys):
        client = _make_client(isolated_paths)

        def boom(self, *a, **k):
            raise httpx.HTTPStatusError("500", request=None, response=None)

        monkeypatch.setattr(RelayClient, "unregister_temp_route", boom)
        _wire_client(monkeypatch, isolated_paths, client)

        rc = cli.main(
            [
                "route",
                "unregister",
                "--path",
                "/upload/err",
                "--method",
                "POST",
            ]
        )
        assert rc == 1
        err = capsys.readouterr().err
        assert "failed to unregister route" in err.lower()


# ---------------------------------------------------------------------------
# route list
# ---------------------------------------------------------------------------


class TestRouteList:
    def test_list_text_output(self, isolated_paths: Path, monkeypatch, capsys):
        client = _make_client(isolated_paths)
        routes = [
            {
                "node_id": "n1",
                "path": "/upload/abc",
                "method": "POST",
                "auth": "node_token",
                "upstream": "http://storage:8791/upload/abc",
                "description": "",
                "expires_at": "2026-08-07T20:00:00+00:00",
                "channel_id": "ch_abc",
            },
            {
                "node_id": "n1",
                "path": "/api/test",
                "method": "GET",
                "auth": "session",
                "upstream": "http://localhost:9999/api/test",
                "description": "Test route",
                "expires_at": None,
                "channel_id": None,
            },
        ]
        monkeypatch.setattr(RelayClient, "list_temp_routes", lambda self: routes)
        _wire_client(monkeypatch, isolated_paths, client)

        rc = cli.main(["route", "list"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Routes (2 total)" in out
        assert "/upload/abc" in out
        assert "/api/test" in out
        assert "temp" in out
        assert "perm" in out
        assert "ch_abc" in out
        assert "permanent" in out

    def test_list_json_output(self, isolated_paths: Path, monkeypatch, capsys):
        client = _make_client(isolated_paths)
        routes = [
            {
                "node_id": "n1",
                "path": "/upload/x",
                "method": "POST",
                "auth": "node_token",
                "upstream": "http://x",
                "description": "",
                "expires_at": "2026-08-07T20:00:00+00:00",
                "channel_id": "ch_x",
            },
        ]
        monkeypatch.setattr(RelayClient, "list_temp_routes", lambda self: routes)
        _wire_client(monkeypatch, isolated_paths, client)

        rc = cli.main(["--json", "route", "list"])
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["path"] == "/upload/x"

    def test_list_empty(self, isolated_paths: Path, monkeypatch, capsys):
        client = _make_client(isolated_paths)
        monkeypatch.setattr(RelayClient, "list_temp_routes", lambda self: [])
        _wire_client(monkeypatch, isolated_paths, client)

        rc = cli.main(["route", "list"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "no routes" in out.lower()

    def test_list_returns_nonzero_on_error(self, isolated_paths: Path, monkeypatch, capsys):
        client = _make_client(isolated_paths)

        def boom(self):
            raise httpx.HTTPStatusError("500", request=None, response=None)

        monkeypatch.setattr(RelayClient, "list_temp_routes", boom)
        _wire_client(monkeypatch, isolated_paths, client)

        rc = cli.main(["route", "list"])
        assert rc == 1
        err = capsys.readouterr().err
        assert "failed to list routes" in err.lower()


# ---------------------------------------------------------------------------
# parser wiring — route subcommands are registered in build_parser()
# ---------------------------------------------------------------------------


class TestRouteParser:
    def test_route_subcommands_in_help(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            cli.main(["route", "--help"])
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        for sub in ("register", "unregister", "list"):
            assert sub in out

    def test_route_subcommands_parse_without_errors(self):
        parser = cli.build_parser()
        cases = [
            [
                "route",
                "register",
                "--path",
                "/upload/x",
                "--method",
                "POST",
                "--upstream",
                "http://x",
                "--ttl",
                "60",
                "--channel",
                "ch_x",
            ],
            [
                "route",
                "register",
                "--path",
                "/upload/x",
                "--method",
                "POST",
                "--upstream",
                "http://x",
                "--ttl",
                "60",
                "--channel",
                "ch_x",
                "--description",
                "note",
            ],
            ["route", "unregister", "--path", "/upload/x", "--method", "POST"],
            ["route", "list"],
        ]
        for argv in cases:
            ns = parser.parse_args(argv)
            assert hasattr(ns, "func"), f"no func set for {argv}"
