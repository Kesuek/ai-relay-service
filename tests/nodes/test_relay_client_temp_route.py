"""Tests for RelayClient temp bridge route helpers (T-126).

Covers :meth:`RelayClient.register_temp_route` and
:meth:`RelayClient.unregister_temp_route`. Both talk to the server's
``/relay/v2/dashboard/api/node-routes/...`` endpoints; we mock
:mod:`httpx` so no network is needed.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

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

    monkeypatch.setattr(node_utils, "BASE_DIR", base)
    monkeypatch.setattr(node_utils, "CONFIG_PATH", base / "relay_config.json")
    monkeypatch.setattr(node_utils, "META_PATH", base / "ai-relay-agent.json")
    monkeypatch.setattr(node_utils, "TOKEN_PATH", base / "ai-relay-agent.token")
    monkeypatch.setattr(node_utils, "STATUS_PATH", base / "worker_status.json")

    profiles_dir.mkdir(parents=True, exist_ok=True)
    return base


def _make_client(isolated_paths: Path) -> RelayClient:
    """Build a RelayClient wired to a fake relay at http://relay.test."""
    # Persist meta + token so RelayClient.__init__ finds them.
    node_utils.write_json_atomic(
        isolated_paths / "ai-relay-agent.json",
        {"node_id": "node-abc", "base_url": "http://relay.test"},
    )
    node_utils.save_token("rt-fake-token", expires_at=None)
    (isolated_paths / "relay_config.json").write_text(
        json.dumps({"base_url": "http://relay.test", "request_timeout": 5})
    )
    meta = node_utils.load_meta()
    cfg = node_utils.load_config()
    return RelayClient(meta, cfg)


class _FakeResponse:
    """Minimal httpx.Response stand-in for the mocked calls below."""

    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = json.dumps(self._payload)

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=None, response=None  # type: ignore[arg-type]
            )


# ---------------------------------------------------------------------------
# register_temp_route
# ---------------------------------------------------------------------------


class TestRegisterTempRoute:
    def test_register_posts_expected_body(self, isolated_paths: Path):
        client = _make_client(isolated_paths)
        captured: dict = {}

        def fake_post(url, *, headers, json, timeout, verify):  # noqa: ARG001
            captured["url"] = url
            captured["headers"] = headers
            captured["body"] = json
            return _FakeResponse(
                200,
                {
                    "status": "ok",
                    "node_id": "node-abc",
                    "path": "/upload/xyz",
                    "method": "POST",
                    "expires_at": "2026-08-07T18:00:00+00:00",
                    "channel_id": "ch_xyz",
                },
            )

        with patch.object(httpx, "post", side_effect=fake_post):
            result = client.register_temp_route(
                "/upload/xyz",
                "POST",
                "http://storage:8791/upload/xyz",
                ttl_seconds=3600,
                channel_id="ch_xyz",
                description="upload channel",
            )

        assert captured["url"] == "http://relay.test/relay/v2/dashboard/api/node-routes/register"
        assert captured["headers"]["Authorization"] == "Bearer rt-fake-token"
        assert captured["body"]["path"] == "/upload/xyz"
        assert captured["body"]["method"] == "POST"
        assert captured["body"]["upstream"] == "http://storage:8791/upload/xyz"
        assert captured["body"]["ttl_seconds"] == 3600
        assert captured["body"]["channel_id"] == "ch_xyz"
        assert captured["body"]["description"] == "upload channel"
        assert result["status"] == "ok"
        assert result["channel_id"] == "ch_xyz"

    def test_register_raises_on_error_status(self, isolated_paths: Path):
        client = _make_client(isolated_paths)

        def fake_post(url, **kw):  # noqa: ARG001
            return _FakeResponse(400, {"detail": "bad request"})

        with patch.object(httpx, "post", side_effect=fake_post):
            with pytest.raises(httpx.HTTPStatusError):
                client.register_temp_route(
                    "/upload/x", "POST", "http://x", ttl_seconds=60, channel_id="ch_x"
                )


# ---------------------------------------------------------------------------
# unregister_temp_route
# ---------------------------------------------------------------------------


class TestUnregisterTempRoute:
    def test_unregister_deletes_with_method_query_param(self, isolated_paths: Path):
        client = _make_client(isolated_paths)
        captured: dict = {}

        def fake_delete(url, *, headers, params, timeout, verify):  # noqa: ARG001
            captured["url"] = url
            captured["headers"] = headers
            captured["params"] = params
            return _FakeResponse(200, {"status": "deleted"})

        with patch.object(httpx, "delete", side_effect=fake_delete):
            client.unregister_temp_route("/upload/del", method="POST")

        assert captured["url"] == (
            "http://relay.test/relay/v2/dashboard/api/node-routes/node-abc/upload/del"
        )
        assert captured["headers"]["Authorization"] == "Bearer rt-fake-token"
        assert captured["params"] == {"method": "POST"}

    def test_unregister_swallows_404(self, isolated_paths: Path):
        """A 404 (route already expired/reaped) is fine — no exception."""
        client = _make_client(isolated_paths)

        def fake_delete(url, **kw):  # noqa: ARG001
            return _FakeResponse(404, {"detail": "not found"})

        with patch.object(httpx, "delete", side_effect=fake_delete):
            # Must not raise.
            client.unregister_temp_route("/upload/gone", method="POST")

    def test_unregister_raises_on_non_2xx_non_404(self, isolated_paths: Path):
        client = _make_client(isolated_paths)

        def fake_delete(url, **kw):  # noqa: ARG001
            return _FakeResponse(403, {"detail": "forbidden"})

        with patch.object(httpx, "delete", side_effect=fake_delete):
            with pytest.raises(httpx.HTTPStatusError):
                client.unregister_temp_route("/upload/forbid", method="POST")

    def test_unregister_normalizes_leading_slash(self, isolated_paths: Path):
        """A path without a leading slash is normalized to start with '/'."""
        client = _make_client(isolated_paths)
        captured: dict = {}

        def fake_delete(url, **kw):  # noqa: ARG001
            captured["url"] = url
            return _FakeResponse(200, {"status": "deleted"})

        with patch.object(httpx, "delete", side_effect=fake_delete):
            client.unregister_temp_route("upload/no-slash", method="POST")

        assert captured["url"].endswith("/node-abc/upload/no-slash")


# ---------------------------------------------------------------------------
# mDNS discovery fallback (T-152)
# ---------------------------------------------------------------------------


class TestMdnsDiscovery:
    def test_base_url_uses_mdns_when_no_url_configured(self, isolated_paths: Path):
        """When no base_url is set, _base_url falls back to mDNS discovery."""
        from nodes.common import relay_client

        # No base_url in config or meta.
        (isolated_paths / "relay_config.json").write_text(json.dumps({}))
        (isolated_paths / "ai-relay-agent.json").write_text(
            json.dumps({"node_id": "node-abc"})
        )
        meta = node_utils.load_meta()
        cfg = node_utils.load_config()

        with patch.object(
            relay_client, "_discover_relay_mdns", return_value="http://192.168.1.50:8788"
        ):
            url = relay_client._base_url(meta, cfg)

        assert url == "http://192.168.1.50:8788"

    def test_base_url_raises_when_mdns_finds_nothing(self, isolated_paths: Path):
        """When no base_url AND mDNS finds nothing, _base_url raises SystemExit."""
        from nodes.common import relay_client

        (isolated_paths / "relay_config.json").write_text(json.dumps({}))
        (isolated_paths / "ai-relay-agent.json").write_text(
            json.dumps({"node_id": "node-abc"})
        )
        meta = node_utils.load_meta()
        cfg = node_utils.load_config()

        with patch.object(relay_client, "_discover_relay_mdns", return_value=None):
            with pytest.raises(SystemExit, match="no base_url"):
                relay_client._base_url(meta, cfg)

    def test_base_url_prefers_configured_url_over_mdns(self, isolated_paths: Path):
        """A configured base_url wins; mDNS is not consulted."""
        from nodes.common import relay_client

        (isolated_paths / "relay_config.json").write_text(
            json.dumps({"base_url": "http://relay.test"})
        )
        (isolated_paths / "ai-relay-agent.json").write_text(
            json.dumps({"node_id": "node-abc"})
        )
        meta = node_utils.load_meta()
        cfg = node_utils.load_config()

        with patch.object(
            relay_client, "_discover_relay_mdns", return_value="http://wrong:9999"
        ) as mock_mdns:
            url = relay_client._base_url(meta, cfg)

        assert url == "http://relay.test"
        mock_mdns.assert_not_called()