"""Tests for the node daemon's handler timeout logic (T-163)."""
from __future__ import annotations

from nodes.common.node_daemon import _handler_timeout


class TestHandlerTimeout:
    def test_long_run_gets_2h_budget(self):
        """A long_run capability must not be killed by the short per-stage
        timeout — it gets the 2h Long-Run lease budget (T-163)."""
        cap = {"name": "storage.extract", "timeout": 300, "long_run": True}
        assert _handler_timeout(cap) == 2 * 3600

    def test_non_long_run_keeps_configured_timeout(self):
        cap = {"name": "storage.list", "timeout": 120, "long_run": False}
        assert _handler_timeout(cap) == 120

    def test_default_timeout_when_missing(self):
        cap = {"name": "storage.list"}
        assert _handler_timeout(cap) == 300
