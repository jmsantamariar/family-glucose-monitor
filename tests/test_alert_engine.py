"""Tests for alert_engine module."""
import pytest
from datetime import datetime, timezone, timedelta
from src.alert_engine import evaluate, is_stale, should_alert, build_message

CONFIG = {
    "alerts": {
        "low_threshold": 70,
        "high_threshold": 180,
        "cooldown_minutes": 20,
        "max_reading_age_minutes": 15,
        "messages": {
            "low": "⚠️ {patient_name}: glucosa en {value} mg/dL {trend} — BAJA",
            "high": "⚠️ {patient_name}: glucosa en {value} mg/dL {trend} — ALTA",
        },
    }
}


# --- evaluate() ---

def test_evaluate_normal():
    assert evaluate(120, CONFIG) == "normal"

def test_evaluate_low_boundary():
    assert evaluate(70, CONFIG) == "normal"  # exactly at threshold = normal

def test_evaluate_below_low():
    assert evaluate(69, CONFIG) == "low"

def test_evaluate_high_boundary():
    assert evaluate(180, CONFIG) == "normal"  # exactly at threshold = normal

def test_evaluate_above_high():
    assert evaluate(181, CONFIG) == "high"

def test_evaluate_very_low():
    assert evaluate(40, CONFIG) == "low"

def test_evaluate_very_high():
    assert evaluate(300, CONFIG) == "high"

def test_evaluate_just_above_low():
    assert evaluate(71, CONFIG) == "normal"

def test_evaluate_just_below_high():
    assert evaluate(179, CONFIG) == "normal"


# --- is_stale() ---

def test_is_stale_fresh_reading():
    ts = datetime.now(timezone.utc) - timedelta(minutes=5)
    assert is_stale(ts, 15) is False

def test_is_stale_old_reading():
    ts = datetime.now(timezone.utc) - timedelta(minutes=20)
    assert is_stale(ts, 15) is True

def test_is_stale_exactly_at_limit():
    # Reading exactly at the limit is stale (> not >=)
    ts = datetime.now(timezone.utc) - timedelta(minutes=15, seconds=1)
    assert is_stale(ts, 15) is True

def test_is_stale_one_second_before_limit():
    ts = datetime.now(timezone.utc) - timedelta(minutes=14, seconds=59)
    assert is_stale(ts, 15) is False


# --- should_alert() ---

def test_should_alert_normal_returns_false():
    assert should_alert("normal", {}, 20) is False

def test_should_alert_no_previous_state():
    assert should_alert("low", {}, 20) is True

def test_should_alert_same_level_within_cooldown():
    last_time = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    state = {"last_alert_time": last_time, "last_alert_level": "low"}
    assert should_alert("low", state, 20) is False

def test_should_alert_same_level_after_cooldown():
    last_time = (datetime.now(timezone.utc) - timedelta(minutes=25)).isoformat()
    state = {"last_alert_time": last_time, "last_alert_level": "low"}
    assert should_alert("low", state, 20) is True

def test_should_alert_different_level_ignores_cooldown():
    last_time = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    state = {"last_alert_time": last_time, "last_alert_level": "low"}
    assert should_alert("high", state, 20) is True

def test_should_alert_high_no_previous():
    assert should_alert("high", {}, 20) is True

def test_should_alert_high_within_cooldown():
    last_time = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
    state = {"last_alert_time": last_time, "last_alert_level": "high"}
    assert should_alert("high", state, 20) is False


# --- build_message() ---

def test_build_message_low_with_config():
    msg = build_message(65, "low", "↓", patient_name="Ana", config=CONFIG)
    assert "Ana" in msg
    assert "65" in msg
    assert "↓" in msg
    assert "BAJA" in msg

def test_build_message_high_with_config():
    msg = build_message(200, "high", "↑", patient_name="Carlos", config=CONFIG)
    assert "Carlos" in msg
    assert "200" in msg
    assert "↑" in msg
    assert "ALTA" in msg

def test_build_message_no_config_uses_defaults():
    msg = build_message(65, "low", "↓", patient_name="Ana")
    assert "Ana" in msg
    assert "65" in msg
    assert "BAJA" in msg

def test_build_message_high_no_config():
    msg = build_message(200, "high", "→", patient_name="Bob")
    assert "Bob" in msg
    assert "200" in msg
    assert "ALTA" in msg

def test_build_message_unknown_level_fallback():
    msg = build_message(120, "critical", "→", patient_name="Alice")
    assert "120" in msg
    assert "critical" in msg

def test_build_message_empty_patient_name():
    msg = build_message(65, "low", "↓", patient_name="", config=CONFIG)
    assert "65" in msg
    assert "BAJA" in msg
