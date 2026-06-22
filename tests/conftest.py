"""Shared pytest fixtures and test isolation helpers."""

import pytest

from relay_server.api.v2.auth import limiter as auth_limiter
from relay_server.api.v2.dashboard import limiter as dashboard_limiter


def _reset_limiters():
    for limiter in (auth_limiter, dashboard_limiter):
        if hasattr(limiter, "_storage") and limiter._storage is not None:
            limiter._storage.reset()


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    _reset_limiters()
    yield
    _reset_limiters()
