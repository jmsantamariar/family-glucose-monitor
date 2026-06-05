"""Tests for the sensor-silence alert engine (src/alert_engine.py)."""
from datetime import datetime, timedelta, timezone

import pytest

from src.alert_engine import (
    build_silence_message,
    evaluate_silence,
    get_silence_config,
    humanize_minutes,
    is_silence_muted,
    silence_minutes,
)

NOW = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)


def _ts(minutes_ago: float) -> datetime:
    return NOW - timedelta(minutes=minutes_ago)


# ── get_silence_config ───────────────────────────────────────────────────────


def test_defaults_when_no_config():
    cfg = get_silence_config(None)
    assert cfg["enabled"] is True
    assert cfg["check_after_minutes"] == 60
    assert cfg["ask_after_minutes"] == 180
    assert cfg["remind_every_hours"] == 24


def test_config_overrides_defaults():
    cfg = get_silence_config(
        {"alerts": {"silence": {"check_after_minutes": 30, "enabled": False}}}
    )
    assert cfg["check_after_minutes"] == 30
    assert cfg["enabled"] is False
    assert cfg["ask_after_minutes"] == 180  # untouched default


# ── evaluate_silence: stage transitions ──────────────────────────────────────


def test_fresh_reading_no_action():
    assert evaluate_silence(_ts(5), {}, now=NOW) is None


def test_below_check_threshold_no_action():
    assert evaluate_silence(_ts(59), {}, now=NOW) is None


def test_stage1_at_check_threshold():
    assert evaluate_silence(_ts(61), {}, now=NOW) == "stage1"


def test_stage1_not_repeated():
    state = {"stage": "stage1", "last_alert_time": _ts(30).isoformat()}
    assert evaluate_silence(_ts(90), state, now=NOW) is None


def test_stage2_at_ask_threshold():
    state = {"stage": "stage1", "last_alert_time": _ts(120).isoformat()}
    assert evaluate_silence(_ts(181), state, now=NOW) == "stage2"


def test_stage2_directly_when_first_seen_late():
    """First evaluation after 3h+ jumps straight to stage2 (no redundant stage1)."""
    assert evaluate_silence(_ts(200), {}, now=NOW) == "stage2"


def test_reminder_after_24h():
    state = {"stage": "stage2", "last_alert_time": (NOW - timedelta(hours=25)).isoformat()}
    assert evaluate_silence(_ts(60 * 30), state, now=NOW) == "reminder"


def test_no_reminder_before_24h():
    state = {"stage": "stage2", "last_alert_time": (NOW - timedelta(hours=23)).isoformat()}
    assert evaluate_silence(_ts(60 * 30), state, now=NOW) is None


def test_disabled_silences_everything():
    cfg = {"alerts": {"silence": {"enabled": False}}}
    assert evaluate_silence(_ts(60 * 24 * 5), {}, config=cfg, now=NOW) is None


# ── mute ─────────────────────────────────────────────────────────────────────


def test_mute_until_future_suppresses():
    state = {"stage": "stage2", "muted_until": (NOW + timedelta(days=1)).isoformat()}
    assert evaluate_silence(_ts(60 * 30), state, now=NOW) is None


def test_mute_expired_resumes():
    state = {"stage": "stage2",
             "muted_until": (NOW - timedelta(hours=1)).isoformat(),
             "last_alert_time": (NOW - timedelta(hours=30)).isoformat()}
    assert evaluate_silence(_ts(60 * 30), state, now=NOW) == "reminder"


def test_mute_until_recovery_suppresses_indefinitely():
    state = {"stage": "stage2", "muted_until": "recovery"}
    assert evaluate_silence(_ts(60 * 24 * 30), state, now=NOW) is None


def test_is_silence_muted_garbage_value():
    assert is_silence_muted({"muted_until": "not-a-date"}, now=NOW) is False


# ── helpers / messages ───────────────────────────────────────────────────────


def test_silence_minutes():
    assert silence_minutes(_ts(90), now=NOW) == pytest.approx(90)


@pytest.mark.parametrize(
    "minutes,expected",
    [(45, "45 min"), (119, "119 min"), (180, "3h"), (60 * 47, "47h"), (60 * 72, "3 días")],
)
def test_humanize_minutes(minutes, expected):
    assert humanize_minutes(minutes) == expected


def test_stage2_message_wording():
    """Exact wording approved: 'el sensor terminó su vida útil'."""
    msg = build_silence_message("stage2", "Leticia", 185)
    assert "el sensor terminó su vida útil" in msg
    assert "Leticia" in msg
    assert "3h" in msg


def test_recovered_message_includes_reading():
    msg = build_silence_message("recovered", "Mario", 0, glucose_value=98, trend_arrow="→")
    assert "98" in msg and "→" in msg and "Mario" in msg


def test_custom_template_from_config():
    cfg = {"alerts": {"silence": {"messages": {"stage1": "ojo {patient_name} {silence_human}"}}}}
    assert build_silence_message("stage1", "Ana", 75, config=cfg) == "ojo Ana 75 min"


def test_template_injection_blocked():
    cfg = {"alerts": {"silence": {"messages": {"stage1": "{patient_name.__class__}"}}}}
    msg = build_silence_message("stage1", "Ana", 75, config=cfg)
    assert "__class__" in msg  # returned raw, not evaluated
