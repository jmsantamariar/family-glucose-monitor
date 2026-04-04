"""Tests for src/paths.py — centralized path resolution helpers."""
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from src.paths import (
    DEFAULT_CACHE_FILENAME,
    DEFAULT_DB_FILENAME,
    DEFAULT_STATE_FILENAME,
    PROJECT_ROOT,
    get_cache_path,
    get_db_path,
    get_state_path,
)


# ---------------------------------------------------------------------------
# get_cache_path
# ---------------------------------------------------------------------------


class TestGetCachePath:
    def test_default_when_no_config(self):
        result = get_cache_path(None)
        assert result == str(PROJECT_ROOT / DEFAULT_CACHE_FILENAME)

    def test_default_when_empty_config(self):
        assert get_cache_path({}) == str(PROJECT_ROOT / DEFAULT_CACHE_FILENAME)

    def test_custom_relative_path(self):
        config = {"api": {"cache_file": "custom/cache.json"}}
        assert get_cache_path(config) == str(PROJECT_ROOT / "custom" / "cache.json")

    def test_custom_absolute_path(self):
        config = {"api": {"cache_file": "/var/data/cache.json"}}
        assert get_cache_path(config) == "/var/data/cache.json"

    def test_env_var_overrides_config(self, monkeypatch, tmp_path):
        env_path = str(tmp_path / "env_cache.json")
        monkeypatch.setenv("READINGS_CACHE_FILE", env_path)
        config = {"api": {"cache_file": "/other/cache.json"}}
        assert get_cache_path(config) == env_path

    def test_env_var_overrides_default(self, monkeypatch, tmp_path):
        env_path = str(tmp_path / "env_cache.json")
        monkeypatch.setenv("READINGS_CACHE_FILE", env_path)
        assert get_cache_path(None) == env_path

    def test_env_var_cleared_returns_default(self, monkeypatch):
        monkeypatch.delenv("READINGS_CACHE_FILE", raising=False)
        assert get_cache_path(None) == str(PROJECT_ROOT / DEFAULT_CACHE_FILENAME)

    def test_consistency_same_config(self):
        config = {"api": {"cache_file": "readings_cache.json"}}
        assert get_cache_path(config) == get_cache_path(config)

    def test_non_dict_api_section_uses_default(self):
        config = {"api": "not-a-dict"}
        assert get_cache_path(config) == str(PROJECT_ROOT / DEFAULT_CACHE_FILENAME)

    def test_empty_string_cache_file_uses_default(self):
        config = {"api": {"cache_file": ""}}
        assert get_cache_path(config) == str(PROJECT_ROOT / DEFAULT_CACHE_FILENAME)


# ---------------------------------------------------------------------------
# get_db_path
# ---------------------------------------------------------------------------


class TestGetDbPath:
    def test_default_when_no_config(self):
        assert get_db_path(None) == str(PROJECT_ROOT / DEFAULT_DB_FILENAME)

    def test_default_when_empty_config(self):
        assert get_db_path({}) == str(PROJECT_ROOT / DEFAULT_DB_FILENAME)

    def test_custom_relative_path(self):
        config = {"alert_history_db": "data/alerts.db"}
        assert get_db_path(config) == str(PROJECT_ROOT / "data" / "alerts.db")

    def test_custom_absolute_path(self):
        config = {"alert_history_db": "/srv/db/alerts.db"}
        assert get_db_path(config) == "/srv/db/alerts.db"

    def test_env_var_overrides_config(self, monkeypatch, tmp_path):
        env_path = str(tmp_path / "env_alerts.db")
        monkeypatch.setenv("ALERT_HISTORY_DB", env_path)
        config = {"alert_history_db": "/other/alerts.db"}
        assert get_db_path(config) == env_path

    def test_env_var_overrides_default(self, monkeypatch, tmp_path):
        env_path = str(tmp_path / "env_alerts.db")
        monkeypatch.setenv("ALERT_HISTORY_DB", env_path)
        assert get_db_path(None) == env_path

    def test_env_var_cleared_returns_default(self, monkeypatch):
        monkeypatch.delenv("ALERT_HISTORY_DB", raising=False)
        assert get_db_path(None) == str(PROJECT_ROOT / DEFAULT_DB_FILENAME)

    def test_empty_string_db_uses_default(self):
        config = {"alert_history_db": ""}
        assert get_db_path(config) == str(PROJECT_ROOT / DEFAULT_DB_FILENAME)


# ---------------------------------------------------------------------------
# get_state_path
# ---------------------------------------------------------------------------


class TestGetStatePath:
    def test_default_when_no_config(self):
        assert get_state_path(None) == str(PROJECT_ROOT / DEFAULT_STATE_FILENAME)

    def test_default_when_empty_config(self):
        assert get_state_path({}) == str(PROJECT_ROOT / DEFAULT_STATE_FILENAME)

    def test_custom_relative_path(self):
        config = {"state_file": "data/state.json"}
        assert get_state_path(config) == str(PROJECT_ROOT / "data" / "state.json")

    def test_custom_absolute_path(self):
        config = {"state_file": "/var/state.json"}
        assert get_state_path(config) == "/var/state.json"

    def test_env_var_overrides_config(self, monkeypatch, tmp_path):
        env_path = str(tmp_path / "env_state.json")
        monkeypatch.setenv("STATE_FILE", env_path)
        config = {"state_file": "/other/state.json"}
        assert get_state_path(config) == env_path

    def test_env_var_overrides_default(self, monkeypatch, tmp_path):
        env_path = str(tmp_path / "env_state.json")
        monkeypatch.setenv("STATE_FILE", env_path)
        assert get_state_path(None) == env_path

    def test_env_var_cleared_returns_default(self, monkeypatch):
        monkeypatch.delenv("STATE_FILE", raising=False)
        assert get_state_path(None) == str(PROJECT_ROOT / DEFAULT_STATE_FILENAME)

    def test_empty_string_state_uses_default(self):
        config = {"state_file": ""}
        assert get_state_path(config) == str(PROJECT_ROOT / DEFAULT_STATE_FILENAME)
