"""Shared pytest fixtures.

Authentication is disabled by default for all tests so that the existing
test suite for api.py and api_server.py continues to pass without changes.
Tests that need the auth middleware enabled (e.g. test_auth.py) should
override this by calling ``monkeypatch.delenv("AUTH_DISABLED", raising=False)``
inside their own fixtures.
"""
import pytest


@pytest.fixture(autouse=True)
def disable_auth_for_tests(monkeypatch):
    """Set AUTH_DISABLED=1 so the auth middleware is bypassed by default."""
    monkeypatch.setenv("AUTH_DISABLED", "1")
