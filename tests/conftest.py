"""Shared pytest fixtures.

Authentication and CSRF are disabled by default for all tests so that the
existing test suite for api.py and api_server.py continues to pass without
changes.  Tests that specifically exercise security paths should override these
by patching the module flags directly inside their own fixtures.
"""
import pytest


@pytest.fixture(autouse=True)
def disable_auth_for_tests(monkeypatch):
    """Bypass auth middleware and CSRF validation by default in all tests."""
    monkeypatch.setenv("AUTH_DISABLED", "1")
    # Patch the pre-computed module-level flag so auth middleware AND CSRF
    # validation are both skipped.  test_auth.py tests that need real auth
    # will patch these flags to False in their own fixtures.
    import src.api as _api_module
    monkeypatch.setattr(_api_module, "_ALLOW_AUTH_DISABLED", True)
