"""Shared pytest fixtures and test isolation helpers."""

import pytest

from relay_server.api.v2.auth import limiter as auth_limiter
from relay_server.api.v2.dashboard import limiter as dashboard_limiter

# Deterministic session secret for tests. Token operations (_get_token_pepper)
# require settings.session_secret to be >= 32 chars. Some test modules (e.g.
# test_discovery.py) never set it themselves and rely on the dev config;
# setting it here globally makes every test independent of import order and
# of the developer's ~/.relay/config.yaml (T-114 / T-068 class).
_TEST_SESSION_SECRET = "test-session-secret-32-chars-minimum!!!"


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    _reset_limiters()
    yield
    _reset_limiters()


def _reset_limiters():
    for limiter in (auth_limiter, dashboard_limiter):
        if hasattr(limiter, "_storage") and limiter._storage is not None:
            limiter._storage.reset()


@pytest.fixture(autouse=True)
def _default_test_session_secret():
    """Ensure every test has a valid session secret set.

    Prevents cross-module interference: without this, tests that set the
    secret in their own fixture (test_route_registry) can leave the global
    ``settings`` in a state that breaks tests expecting it (test_discovery),
    depending on pytest's import order. This makes the secret deterministic
    and always present.
    """
    from relay_server.config import settings

    settings.session_secret = _TEST_SESSION_SECRET
    yield
