"""Tests for alert_engine module."""
from datetime import datetime, timedelta, timezone

import pytest

from src.alert_engine import build_message, evaluate, is_stale, should_alert


# ---------------------------------------------------------------------------
# evaluate
# ---------------------------------------------------------------------------

CONFIG = {"alerts": {"low_threshold": 70, "high_threshold": 180}}


def test_evaluate_low():
    assert evaluate(55, CONFIG) == "low"


def test_evaluate_high():
    assert evaluate(200, CONFIG) == "high"


def test_evaluate_normal():
    assert evaluate(120, CONFIG) == "normal"


def test_evaluate_boundary_low_is_normal():
    # equal to low_threshold → not low
    assert evaluate(70, CONFIG) == "normal"


def test_evaluate_boundary_high_is_normal():
    # equal to high_threshold → not high
    assert evaluate(180, CONFIG) == "normal"


def test_evaluate_just_below_low():
    assert evaluate(69, CONFIG) == "low"


def test_evaluate_just_above_high():
    assert evaluate(181, CONFIG) == "high"


# ---------------------------------------------------------------------------
# is_stale
# ---------------------------------------------------------------------------

def test_is_stale_fresh():
    ts = datetime.now(timezone.utc) - timedelta(minutes=5)
    assert is_stale(ts, max_age_minutes=15) is False


def test_is_stale_old():
    ts = datetime.now(timezone.utc) - timedelta(minutes=20)
    assert is_stale(ts, max_age_minutes=15) is True


def test_is_stale_boundary_just_under_limit():
    # Just under max_age → not stale
    ts = datetime.now(timezone.utc) - timedelta(minutes=14, seconds=59)
    assert is_stale(ts, max_age_minutes=15) is False


def test_is_stale_one_second_over():
    ts = datetime.now(timezone.utc) - timedelta(minutes=15, seconds=1)
    assert is_stale(ts, max_age_minutes=15) is True


# ---------------------------------------------------------------------------
# should_alert
# ---------------------------------------------------------------------------

def test_should_alert_normal_returns_false():
    assert should_alert("normal", {}, cooldown_minutes=20) is False


def test_should_alert_first_time_low():
    assert should_alert("low", {}, cooldown_minutes=20) is True


def test_should_alert_first_time_high():
    assert should_alert("high", {}, cooldown_minutes=20) is True


def test_should_alert_level_change():
    state = {
        "last_alert_time": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
        "last_alert_level": "low",
    }
    assert should_alert("high", state, cooldown_minutes=20) is True


def test_should_alert_cooldown_active():
    state = {
        "last_alert_time": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
        "last_alert_level": "high",
    }
    assert should_alert("high", state, cooldown_minutes=20) is False


def test_should_alert_cooldown_expired():
    state = {
        "last_alert_time": (datetime.now(timezone.utc) - timedelta(minutes=25)).isoformat(),
        "last_alert_level": "high",
    }
    assert should_alert("high", state, cooldown_minutes=20) is True


# ---------------------------------------------------------------------------
# build_message
# ---------------------------------------------------------------------------

def test_build_message_default_low():
    msg = build_message(55, "low", "↓", "Mamá")
    assert "Mamá" in msg
    assert "55" in msg
    assert "↓" in msg
    assert "BAJA" in msg


def test_build_message_default_high():
    msg = build_message(250, "high", "↑", "Papá")
    assert "Papá" in msg
    assert "250" in msg
    assert "↑" in msg
    assert "ALTA" in msg


def test_build_message_custom_template():
    config = {
        "alerts": {
            "messages": {
                "low": "ALERTA {patient_name} tiene {value} ({trend})",
            }
        }
    }
    msg = build_message(60, "low", "→", "Juan", config)
    assert msg == "ALERTA Juan tiene 60 (→)"


def test_build_message_patient_name_included():
    msg = build_message(200, "high", "↑", "Ana García", None)
    assert "Ana García" in msg


def test_build_message_unknown_level_fallback():
    msg = build_message(100, "unknown_level", "→", "Test")
    assert "Test" in msg
    assert "100" in msg
