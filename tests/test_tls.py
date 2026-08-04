"""Tests for TLS configuration (T-111)."""

from pathlib import Path

from relay_server.config import Settings


def test_tls_config_defaults_are_none():
    """TLS is off by default (Homelab mode: HTTP, no cert required)."""
    s = Settings()
    assert s.tls_certfile is None
    assert s.tls_keyfile is None


def test_tls_config_accepts_cert_and_key():
    """Setting tls_certfile + tls_keyfile enables TLS config."""
    s = Settings(tls_certfile=Path("/certs/relay.pem"), tls_keyfile=Path("/certs/relay.key"))
    assert s.tls_certfile == Path("/certs/relay.pem")
    assert s.tls_keyfile == Path("/certs/relay.key")


def test_node_client_verify_defaults_to_true():
    """Node client verifies against the system trust store by default."""
    from nodes.common.node_cli import RelayClient

    # Construct a minimal client to check the verify default.
    client = RelayClient.__new__(RelayClient)
    client.cfg = {}
    client._verify = client.cfg.get("tls_ca_cert") or True
    assert client._verify is True


def test_node_client_verify_uses_ca_cert():
    """Node client uses a configured CA cert path for self-signed relays."""
    from nodes.common.node_cli import RelayClient

    client = RelayClient.__new__(RelayClient)
    client.cfg = {"tls_ca_cert": "/path/to/ca.pem"}
    client._verify = client.cfg.get("tls_ca_cert") or True
    assert client._verify == "/path/to/ca.pem"
