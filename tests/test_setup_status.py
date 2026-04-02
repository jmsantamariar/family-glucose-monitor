"""Tests for src.setup_status — check_setup() and is_setup_complete()."""
import textwrap

import pytest
import yaml

from src.setup_status import SetupStatus, check_setup, is_setup_complete


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_yaml(path, content: dict) -> None:
    path.write_text(
        yaml.safe_dump(content, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )


# Minimal config that passes validate_config() in full (all required sections).
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
            + "aabbccdd" * 4  # 32-char salt_hex
            + ":"
            + "eeff0011" * 8  # 64-char key_hex
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
}


# ---------------------------------------------------------------------------
# check_setup() — file-missing cases
# ---------------------------------------------------------------------------

class TestCheckSetupMissingFile:
    def test_returns_incomplete(self, tmp_path):
        path = tmp_path / "config.yaml"
        result = check_setup(path)
        assert result.complete is False

    def test_has_meaningful_error(self, tmp_path):
        path = tmp_path / "config.yaml"
        result = check_setup(path)
        assert any("not found" in e for e in result.errors)

    def test_returns_setup_status_type(self, tmp_path):
        path = tmp_path / "config.yaml"
        result = check_setup(path)
        assert isinstance(result, SetupStatus)


# ---------------------------------------------------------------------------
# check_setup() — empty / non-mapping YAML
# ---------------------------------------------------------------------------

class TestCheckSetupEmptyOrBadYaml:
    def test_empty_file_not_complete(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text("", encoding="utf-8")
        result = check_setup(path)
        assert result.complete is False

    def test_null_yaml_not_complete(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text("~\n", encoding="utf-8")
        result = check_setup(path)
        assert result.complete is False

    def test_null_yaml_has_error(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text("~\n", encoding="utf-8")
        result = check_setup(path)
        assert result.errors

    def test_invalid_yaml_syntax_not_complete(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text("key: [unclosed bracket\n", encoding="utf-8")
        result = check_setup(path)
        assert result.complete is False

    def test_invalid_yaml_has_parse_error(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text("key: [unclosed bracket\n", encoding="utf-8")
        result = check_setup(path)
        assert any("parse error" in e for e in result.errors)

    def test_list_root_not_complete(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text("- item1\n- item2\n", encoding="utf-8")
        result = check_setup(path)
        assert result.complete is False


# ---------------------------------------------------------------------------
# check_setup() — schema validation failures
# ---------------------------------------------------------------------------

class TestCheckSetupSchemaErrors:
    def test_missing_librelinkup_not_complete(self, tmp_path):
        cfg = dict(_VALID_CONFIG)
        del cfg["librelinkup"]
        path = tmp_path / "config.yaml"
        _write_yaml(path, cfg)
        result = check_setup(path)
        assert result.complete is False

    def test_missing_alerts_not_complete(self, tmp_path):
        cfg = dict(_VALID_CONFIG)
        del cfg["alerts"]
        path = tmp_path / "config.yaml"
        _write_yaml(path, cfg)
        result = check_setup(path)
        assert result.complete is False

    def test_schema_errors_are_populated(self, tmp_path):
        cfg = {k: v for k, v in _VALID_CONFIG.items() if k not in ("librelinkup", "alerts")}
        path = tmp_path / "config.yaml"
        _write_yaml(path, cfg)
        result = check_setup(path)
        assert len(result.errors) >= 2  # at least two missing-section errors

    def test_invalid_thresholds_not_complete(self, tmp_path):
        cfg = {**_VALID_CONFIG, "alerts": {**_VALID_CONFIG["alerts"], "low_threshold": 200, "high_threshold": 100}}
        path = tmp_path / "config.yaml"
        _write_yaml(path, cfg)
        result = check_setup(path)
        assert result.complete is False


# ---------------------------------------------------------------------------
# check_setup() — valid config
# ---------------------------------------------------------------------------

class TestCheckSetupValidConfig:
    def test_complete_is_true(self, tmp_path):
        path = tmp_path / "config.yaml"
        _write_yaml(path, _VALID_CONFIG)
        result = check_setup(path)
        assert result.complete is True

    def test_no_errors(self, tmp_path):
        path = tmp_path / "config.yaml"
        _write_yaml(path, _VALID_CONFIG)
        result = check_setup(path)
        assert result.errors == []

    def test_returns_setup_status(self, tmp_path):
        path = tmp_path / "config.yaml"
        _write_yaml(path, _VALID_CONFIG)
        result = check_setup(path)
        assert isinstance(result, SetupStatus)


# ---------------------------------------------------------------------------
# check_setup() — default path fallback (no argument)
# ---------------------------------------------------------------------------

class TestCheckSetupDefaultPath:
    def test_uses_project_root_by_default(self, tmp_path, monkeypatch):
        """check_setup() with no argument reads PROJECT_ROOT/config.yaml."""
        import src.setup_status as ss
        monkeypatch.setattr(ss, "PROJECT_ROOT", tmp_path)
        # File does not exist yet
        result = check_setup()
        assert result.complete is False

    def test_default_path_finds_valid_config(self, tmp_path, monkeypatch):
        import src.setup_status as ss
        monkeypatch.setattr(ss, "PROJECT_ROOT", tmp_path)
        path = tmp_path / "config.yaml"
        _write_yaml(path, _VALID_CONFIG)
        result = check_setup()
        assert result.complete is True


# ---------------------------------------------------------------------------
# is_setup_complete() — convenience wrapper
# ---------------------------------------------------------------------------

class TestIsSetupComplete:
    def test_false_when_missing(self, tmp_path):
        assert is_setup_complete(tmp_path / "config.yaml") is False

    def test_false_when_invalid(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text("not_a_mapping: [broken", encoding="utf-8")
        assert is_setup_complete(path) is False

    def test_true_when_valid(self, tmp_path):
        path = tmp_path / "config.yaml"
        _write_yaml(path, _VALID_CONFIG)
        assert is_setup_complete(path) is True

    def test_returns_bool(self, tmp_path):
        path = tmp_path / "config.yaml"
        result = is_setup_complete(path)
        assert isinstance(result, bool)
