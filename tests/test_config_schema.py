"""Tests for config_schema validation module."""
import os

import pytest

from src.config_schema import validate_config


# ---------------------------------------------------------------------------
# Minimal valid config fixture
# ---------------------------------------------------------------------------

def _valid_config():
    return {
        "librelinkup": {
            "email": "user@example.com",
            "password": "secret",
            "region": "EU",
        },
        "alerts": {
            "low_threshold": 70,
            "high_threshold": 180,
            "cooldown_minutes": 20,
            "max_reading_age_minutes": 15,
        },
        "outputs": [
            {"type": "telegram", "enabled": True, "bot_token": "tok", "chat_id": "123"},
        ],
    }


# ---------------------------------------------------------------------------
# valid config
# ---------------------------------------------------------------------------

def test_valid_config_returns_no_errors():
    assert validate_config(_valid_config()) == []


def test_non_dict_config():
    errors = validate_config("not a dict")
    assert any("dict" in e for e in errors)


# ---------------------------------------------------------------------------
# librelinkup section
# ---------------------------------------------------------------------------

def test_missing_librelinkup_section():
    cfg = _valid_config()
    del cfg["librelinkup"]
    errors = validate_config(cfg)
    assert any("librelinkup" in e for e in errors)


def test_missing_email_no_env(monkeypatch):
    monkeypatch.delenv("LIBRELINKUP_EMAIL", raising=False)
    cfg = _valid_config()
    cfg["librelinkup"]["email"] = ""
    errors = validate_config(cfg)
    assert any("email" in e for e in errors)


def test_invalid_email_format():
    cfg = _valid_config()
    cfg["librelinkup"]["email"] = "not-an-email"
    errors = validate_config(cfg)
    assert any("email" in e for e in errors)


def test_invalid_email_missing_tld():
    cfg = _valid_config()
    cfg["librelinkup"]["email"] = "user@domain"
    errors = validate_config(cfg)
    assert any("email" in e for e in errors)


def test_invalid_email_double_at():
    cfg = _valid_config()
    cfg["librelinkup"]["email"] = "user@@domain.com"
    errors = validate_config(cfg)
    assert any("email" in e for e in errors)


def test_valid_email_via_env(monkeypatch):
    monkeypatch.setenv("LIBRELINKUP_EMAIL", "env@example.com")
    cfg = _valid_config()
    cfg["librelinkup"]["email"] = ""
    errors = validate_config(cfg)
    assert not any("email" in e for e in errors)


def test_missing_password_no_env(monkeypatch):
    monkeypatch.delenv("LIBRELINKUP_PASSWORD", raising=False)
    cfg = _valid_config()
    cfg["librelinkup"]["password"] = ""
    errors = validate_config(cfg)
    assert any("password" in e for e in errors)


def test_valid_password_via_env(monkeypatch):
    monkeypatch.setenv("LIBRELINKUP_PASSWORD", "envpass")
    cfg = _valid_config()
    cfg["librelinkup"]["password"] = ""
    errors = validate_config(cfg)
    assert not any("password" in e for e in errors)


# ---------------------------------------------------------------------------
# alerts section
# ---------------------------------------------------------------------------

def test_missing_alerts_section():
    cfg = _valid_config()
    del cfg["alerts"]
    errors = validate_config(cfg)
    assert any("alerts" in e for e in errors)


def test_low_threshold_missing():
    cfg = _valid_config()
    del cfg["alerts"]["low_threshold"]
    errors = validate_config(cfg)
    assert any("low_threshold" in e for e in errors)


def test_high_threshold_missing():
    cfg = _valid_config()
    del cfg["alerts"]["high_threshold"]
    errors = validate_config(cfg)
    assert any("high_threshold" in e for e in errors)


def test_low_not_less_than_high():
    cfg = _valid_config()
    cfg["alerts"]["low_threshold"] = 180
    cfg["alerts"]["high_threshold"] = 70
    errors = validate_config(cfg)
    assert any("low_threshold" in e and "high_threshold" in e for e in errors)


def test_low_equals_high():
    cfg = _valid_config()
    cfg["alerts"]["low_threshold"] = 100
    cfg["alerts"]["high_threshold"] = 100
    errors = validate_config(cfg)
    assert any("low_threshold" in e for e in errors)


def test_cooldown_zero():
    cfg = _valid_config()
    cfg["alerts"]["cooldown_minutes"] = 0
    errors = validate_config(cfg)
    assert any("cooldown_minutes" in e for e in errors)


def test_cooldown_negative():
    cfg = _valid_config()
    cfg["alerts"]["cooldown_minutes"] = -5
    errors = validate_config(cfg)
    assert any("cooldown_minutes" in e for e in errors)


def test_max_reading_age_zero():
    cfg = _valid_config()
    cfg["alerts"]["max_reading_age_minutes"] = 0
    errors = validate_config(cfg)
    assert any("max_reading_age_minutes" in e for e in errors)


def test_threshold_not_a_number():
    cfg = _valid_config()
    cfg["alerts"]["low_threshold"] = "seventy"
    errors = validate_config(cfg)
    assert any("low_threshold" in e for e in errors)


# ---------------------------------------------------------------------------
# outputs section
# ---------------------------------------------------------------------------

def test_no_enabled_outputs():
    cfg = _valid_config()
    cfg["outputs"][0]["enabled"] = False
    errors = validate_config(cfg)
    assert any("output" in e.lower() for e in errors)


def test_empty_outputs_list():
    cfg = _valid_config()
    cfg["outputs"] = []
    errors = validate_config(cfg)
    assert any("output" in e.lower() for e in errors)


def test_unknown_output_type():
    cfg = _valid_config()
    cfg["outputs"].append({"type": "sms", "enabled": True})
    errors = validate_config(cfg)
    assert any("sms" in e for e in errors)


def test_multiple_outputs_one_enabled():
    cfg = _valid_config()
    cfg["outputs"].append({"type": "webhook", "enabled": False, "url": ""})
    errors = validate_config(cfg)
    assert errors == []


def test_outputs_not_a_list():
    cfg = _valid_config()
    cfg["outputs"] = "telegram"
    errors = validate_config(cfg)
    assert any("list" in e for e in errors)
