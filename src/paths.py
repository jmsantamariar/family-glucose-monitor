"""Centralized helpers for resolving persistent-storage paths.

Priority for every path: environment variable > config key > project default.

Environment variables
---------------------
* ``READINGS_CACHE_FILE`` — override the readings cache JSON path.
* ``ALERT_HISTORY_DB``    — override the alert history SQLite DB path.
* ``STATE_FILE``          — override the state JSON path.

These are checked at *call time* so tests can set them via ``monkeypatch.setenv``
without reloading the module.
"""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Environment variable names
_CACHE_ENV_VAR = "READINGS_CACHE_FILE"
_DB_ENV_VAR = "ALERT_HISTORY_DB"
_STATE_ENV_VAR = "STATE_FILE"

# Default filenames (relative to PROJECT_ROOT)
DEFAULT_CACHE_FILENAME = "readings_cache.json"
DEFAULT_DB_FILENAME = "alert_history.db"
DEFAULT_STATE_FILENAME = "state.json"


def _resolve(env_var: str, cfg_value: str | None, default_name: str) -> str:
    """Return the first non-empty path from: env var → cfg value → default."""
    env_val = os.environ.get(env_var)
    if env_val:
        return env_val
    if isinstance(cfg_value, str) and cfg_value:
        if os.path.isabs(cfg_value):
            return cfg_value
        return str(PROJECT_ROOT / cfg_value)
    return str(PROJECT_ROOT / default_name)


def get_cache_path(config: dict | None = None) -> str:
    """Return the absolute path to the readings cache JSON file.

    Resolution order:
    1. ``READINGS_CACHE_FILE`` environment variable.
    2. ``config["api"]["cache_file"]`` (relative paths resolved against PROJECT_ROOT).
    3. ``<PROJECT_ROOT>/readings_cache.json``.
    """
    cfg_value: str | None = None
    if isinstance(config, dict):
        api_cfg = config.get("api")
        if isinstance(api_cfg, dict):
            cfg_value = api_cfg.get("cache_file") or None
    return _resolve(_CACHE_ENV_VAR, cfg_value, DEFAULT_CACHE_FILENAME)


def get_db_path(config: dict | None = None) -> str:
    """Return the absolute path to the alert history SQLite database.

    Resolution order:
    1. ``ALERT_HISTORY_DB`` environment variable.
    2. ``config["alert_history_db"]`` (relative paths resolved against PROJECT_ROOT).
    3. ``<PROJECT_ROOT>/alert_history.db``.
    """
    cfg_value: str | None = None
    if isinstance(config, dict):
        cfg_value = config.get("alert_history_db") or None
    return _resolve(_DB_ENV_VAR, cfg_value, DEFAULT_DB_FILENAME)


def get_state_path(config: dict | None = None) -> str:
    """Return the absolute path to the daemon state JSON file.

    Resolution order:
    1. ``STATE_FILE`` environment variable.
    2. ``config["state_file"]`` (relative paths resolved against PROJECT_ROOT).
    3. ``<PROJECT_ROOT>/state.json``.
    """
    cfg_value: str | None = None
    if isinstance(config, dict):
        cfg_value = config.get("state_file") or None
    return _resolve(_STATE_ENV_VAR, cfg_value, DEFAULT_STATE_FILENAME)
