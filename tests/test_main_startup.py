"""Tests for main() startup behavior in src.main.

Verifies that:
- A missing config.yaml causes startup in setup-only mode (no sys.exit).
- An empty / invalid YAML config causes startup in setup-only mode.
- A config that fails schema validation causes startup in setup-only mode.
- A valid config results in normal startup (run_once / daemon / dashboard).

All tests mock ``_start_dashboard`` and ``run_once`` to avoid actually
starting uvicorn or making real API calls.
"""
import copy
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml


# ---------------------------------------------------------------------------
# Minimal valid config (cron mode — exercises the simplest normal path)
# ---------------------------------------------------------------------------

_VALID_CONFIG = {
    "librelinkup": {
        "email": "user@example.com",
        "password": "secret123",
        "region": "EU",
    },
    "dashboard_auth": {
        "username": "admin",
        "password_hash": (
            "pbkdf2:sha256:260000:"
            + "aabbccdd" * 4
            + ":"
            + "eeff0011" * 8
        ),
    },
    "alerts": {
        "low_threshold": 70,
        "high_threshold": 180,
        "cooldown_minutes": 30,
        "max_reading_age_minutes": 15,
    },
    "outputs": [
        {
            "type": "telegram",
            "enabled": True,
            "bot_token": "123:ABC",
            "chat_id": "456",
        }
    ],
    "monitoring": {"mode": "cron"},
    "state_file": "",
    "alert_history_db": "",
}


def _write_yaml(path: Path, content: dict) -> None:
    path.write_text(
        yaml.safe_dump(content, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Setup-mode startup tests
# ---------------------------------------------------------------------------

class TestSetupModeStartup:
    """main() should enter setup-only mode (not exit) when config is bad."""

    def _run_main_with_no_config(self, tmp_path):
        """Run main() with PROJECT_ROOT pointing to a dir without config.yaml."""
        import src.main as main_mod
        with (
            patch.object(main_mod, "PROJECT_ROOT", tmp_path),
            patch.object(main_mod, "_start_dashboard") as mock_dash,
        ):
            main_mod.main()
        return mock_dash

    def test_missing_config_does_not_exit(self, tmp_path):
        """main() must NOT call sys.exit when config.yaml is absent."""
        import src.main as main_mod
        with (
            patch.object(main_mod, "PROJECT_ROOT", tmp_path),
            patch.object(main_mod, "_start_dashboard"),
        ):
            # Should return normally, not raise SystemExit
            main_mod.main()

    def test_missing_config_starts_dashboard(self, tmp_path):
        """main() calls _start_dashboard when config.yaml is absent."""
        mock_dash = self._run_main_with_no_config(tmp_path)
        mock_dash.assert_called_once()

    def test_missing_config_dashboard_called_with_empty_dict(self, tmp_path):
        """Setup-mode dashboard is started with an empty config dict."""
        mock_dash = self._run_main_with_no_config(tmp_path)
        args, _ = mock_dash.call_args
        assert args[0] == {}

    def test_empty_config_file_starts_setup_mode(self, tmp_path):
        """An empty config.yaml (None YAML) also enters setup mode."""
        (tmp_path / "config.yaml").write_text("", encoding="utf-8")
        import src.main as main_mod
        with (
            patch.object(main_mod, "PROJECT_ROOT", tmp_path),
            patch.object(main_mod, "_start_dashboard") as mock_dash,
        ):
            main_mod.main()
        mock_dash.assert_called_once_with({})

    def test_invalid_yaml_starts_setup_mode(self, tmp_path):
        """A config.yaml with a YAML parse error enters setup mode."""
        (tmp_path / "config.yaml").write_text("key: [unclosed\n", encoding="utf-8")
        import src.main as main_mod
        with (
            patch.object(main_mod, "PROJECT_ROOT", tmp_path),
            patch.object(main_mod, "_start_dashboard") as mock_dash,
        ):
            main_mod.main()
        mock_dash.assert_called_once_with({})

    def test_schema_invalid_config_starts_setup_mode(self, tmp_path):
        """A config.yaml that fails schema validation enters setup mode."""
        # Missing required sections
        bad_config = {"librelinkup": {"email": "bad-email", "password": ""}}
        _write_yaml(tmp_path / "config.yaml", bad_config)
        import src.main as main_mod
        with (
            patch.object(main_mod, "PROJECT_ROOT", tmp_path),
            patch.object(main_mod, "_start_dashboard") as mock_dash,
        ):
            main_mod.main()
        mock_dash.assert_called_once_with({})


# ---------------------------------------------------------------------------
# Normal-mode startup tests
# ---------------------------------------------------------------------------

class TestNormalModeStartup:
    """main() should follow the normal execution path when config is valid."""

    def test_valid_config_cron_calls_run_once(self, tmp_path):
        """A valid cron-mode config triggers run_once(), not setup mode."""
        cfg = copy.deepcopy(_VALID_CONFIG)
        cfg["state_file"] = str(tmp_path / "state.json")
        cfg["alert_history_db"] = str(tmp_path / "history.db")
        _write_yaml(tmp_path / "config.yaml", cfg)

        import src.main as main_mod
        with (
            patch.object(main_mod, "PROJECT_ROOT", tmp_path),
            patch.object(main_mod, "_start_dashboard") as mock_dash,
            patch.object(main_mod, "run_once") as mock_run,
            patch.object(main_mod, "acquire_lock", return_value=None),
            patch.object(main_mod, "release_lock"),
        ):
            main_mod.main()

        mock_run.assert_called_once()
        mock_dash.assert_not_called()

    def test_valid_config_dashboard_mode_calls_start_dashboard(self, tmp_path):
        """dashboard mode: _start_dashboard is called with the real config."""
        cfg = copy.deepcopy(_VALID_CONFIG)
        cfg["monitoring"] = {"mode": "dashboard"}
        cfg["outputs"] = []  # no outputs needed for dashboard mode
        cfg["state_file"] = str(tmp_path / "state.json")
        cfg["alert_history_db"] = str(tmp_path / "history.db")
        _write_yaml(tmp_path / "config.yaml", cfg)

        import src.main as main_mod
        with (
            patch.object(main_mod, "PROJECT_ROOT", tmp_path),
            patch.object(main_mod, "_start_dashboard") as mock_dash,
        ):
            main_mod.main()

        mock_dash.assert_called_once()
        args, _ = mock_dash.call_args
        assert args[0] != {}  # real config, not empty dict

    def test_valid_config_does_not_enter_setup_mode(self, tmp_path):
        """A valid config must never call _start_dashboard with empty dict."""
        cfg = copy.deepcopy(_VALID_CONFIG)
        cfg["state_file"] = str(tmp_path / "state.json")
        cfg["alert_history_db"] = str(tmp_path / "history.db")
        _write_yaml(tmp_path / "config.yaml", cfg)

        import src.main as main_mod
        setup_mode_calls = []

        def _mock_start_dashboard(config):
            if config == {}:
                setup_mode_calls.append(config)

        with (
            patch.object(main_mod, "PROJECT_ROOT", tmp_path),
            patch.object(main_mod, "_start_dashboard", side_effect=_mock_start_dashboard),
            patch.object(main_mod, "run_once"),
            patch.object(main_mod, "acquire_lock", return_value=None),
            patch.object(main_mod, "release_lock"),
        ):
            main_mod.main()

        assert setup_mode_calls == [], "Normal startup must not enter setup mode"
