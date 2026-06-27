"""Tests for mDNS / Zeroconf registration."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from relay_server.config import settings
from relay_server.core.db import init_db
from relay_server.core.zeroconf import RelayZeroconf, _local_ip
from relay_server.main import app


@pytest.fixture(autouse=True)
def _fresh_db(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        artifacts_dir = Path(tmp) / "artifacts"
        monkeypatch.setattr(settings, "db_path", db_path)
        monkeypatch.setattr(settings, "artifacts_dir", artifacts_dir)
        monkeypatch.setattr(settings, "enable_mdns", False)
        init_db()
        yield


def test_local_ip_returns_ipv4_loopback_or_routable():
    ip = _local_ip()
    parts = ip.split(".")
    assert len(parts) == 4
    for part in parts:
        assert part.isdigit()
        assert 0 <= int(part) <= 255


def test_relay_zeroconf_start_stop():
    zc = RelayZeroconf(hostname="test-relay", port=9876, addresses=["127.0.0.1"])
    with patch("relay_server.core.zeroconf.Zeroconf") as mock_zc_class:
        mock_instance = MagicMock()
        mock_zc_class.return_value = mock_instance
        zc.start()
        assert zc.zeroconf is not None
        mock_instance.register_service.assert_called_once()
        zc.stop()
        mock_instance.unregister_service.assert_called_once()
        mock_instance.close.assert_called_once()


def test_relay_zeroconf_start_handles_errors():
    zc = RelayZeroconf(hostname="test-relay", port=9876, addresses=["127.0.0.1"])
    with patch("relay_server.core.zeroconf.Zeroconf") as mock_zc_class:
        mock_zc_class.side_effect = RuntimeError("mDNS not available")
        zc.start()
        assert zc.zeroconf is None


def test_server_lifespan_when_mdns_enabled(monkeypatch):
    monkeypatch.setattr(settings, "enable_mdns", True)
    with patch("relay_server.main.RelayZeroconf") as mock_zc_class:
        mock_instance = MagicMock()
        mock_zc_class.return_value = mock_instance
        client = TestClient(app)
        with client:
            r = client.get("/health")
            assert r.status_code == 200
        mock_instance.start.assert_called_once()
        mock_instance.stop.assert_called_once()


def test_server_lifespan_when_mdns_disabled(monkeypatch):
    monkeypatch.setattr(settings, "enable_mdns", False)
    with patch("relay_server.main.RelayZeroconf") as mock_zc_class:
        mock_instance = MagicMock()
        mock_zc_class.return_value = mock_instance
        client = TestClient(app)
        with client:
            r = client.get("/health")
            assert r.status_code == 200
        mock_instance.start.assert_not_called()
        mock_instance.stop.assert_not_called()
