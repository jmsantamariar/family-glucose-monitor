"""Tests for trend-based alert features in alert_engine."""
from datetime import datetime, timedelta, timezone

import pytest

from src.alert_engine import (
    TREND_ARROWS,
    classify_trend,
    evaluate_trend,
    should_alert,
    build_message,
)

# ── Config helpers ──────────────────────────────────────────────────────────

TREND_CONFIG = {
    "alerts": {
        "low_threshold": 70,
        "high_threshold": 180,
        "trend": {
            "enabled": True,
            "low_approaching_threshold": 100,
            "high_approaching_threshold": 150,
        },
    }
}

TREND_DISABLED_CONFIG = {
    "alerts": {
        "low_threshold": 70,
        "high_threshold": 180,
        "trend": {
            "enabled": False,
        },
    }
}

NO_TREND_CONFIG = {
    "alerts": {
        "low_threshold": 70,
        "high_threshold": 180,
    }
}


# ── classify_trend ──────────────────────────────────────────────────────────

class TestClassifyTrend:
    def test_unicode_up_arrow(self):
        assert classify_trend("↑") == "rising_fast"

    def test_unicode_forty_five_up(self):
        assert classify_trend("↗") == "rising"

    def test_unicode_flat(self):
        assert classify_trend("→") == "stable"

    def test_unicode_forty_five_down(self):
        assert classify_trend("↘") == "falling"

    def test_unicode_down_arrow(self):
        assert classify_trend("↓") == "falling_fast"

    def test_text_single_up(self):
        assert classify_trend("SingleUp") == "rising_fast"

    def test_text_forty_five_up(self):
        assert classify_trend("FortyFiveUp") == "rising"

    def test_text_flat(self):
        assert classify_trend("Flat") == "stable"

    def test_text_forty_five_down(self):
        assert classify_trend("FortyFiveDown") == "falling"

    def test_text_single_down(self):
        assert classify_trend("SingleDown") == "falling_fast"

    def test_unknown_arrow_returns_unknown(self):
        assert classify_trend("SomethingElse") == "unknown"

    def test_empty_string_returns_unknown(self):
        assert classify_trend("") == "unknown"

    def test_all_arrows_in_dict_covered(self):
        for arrow, expected in TREND_ARROWS.items():
            assert classify_trend(arrow) == expected


# ── evaluate_trend ──────────────────────────────────────────────────────────

class TestEvaluateTrend:
    def test_falling_fast_always_dangerous(self):
        # glucose 95, falling fast → falling_fast
        assert evaluate_trend(95, "↓", TREND_CONFIG) == "falling_fast"

    def test_falling_fast_even_at_low_glucose(self):
        # glucose 50, falling fast → falling_fast (worst case)
        assert evaluate_trend(50, "SingleDown", TREND_CONFIG) == "falling_fast"

    def test_falling_fast_even_at_normal_glucose(self):
        # glucose 120 falling fast → still dangerous
        assert evaluate_trend(120, "↓", TREND_CONFIG) == "falling_fast"

    def test_approaching_hypo_falling(self):
        # glucose 85 (< 100), falling → alert
        assert evaluate_trend(85, "↘", TREND_CONFIG) == "falling"

    def test_approaching_hypo_at_boundary(self):
        # glucose 99 (< 100), falling → alert
        assert evaluate_trend(99, "FortyFiveDown", TREND_CONFIG) == "falling"

    def test_no_alert_when_glucose_above_low_warn_and_falling(self):
        # glucose 110 falling (but not below threshold) → normal
        assert evaluate_trend(110, "↘", TREND_CONFIG) == "normal"

    def test_approaching_hyper_rising_fast(self):
        # glucose 160 (> 150), rising fast → rising_fast
        assert evaluate_trend(160, "↑", TREND_CONFIG) == "rising_fast"

    def test_approaching_hyper_rising(self):
        # glucose 155, rising → rising
        assert evaluate_trend(155, "↗", TREND_CONFIG) == "rising"

    def test_approaching_hyper_at_boundary(self):
        # glucose 151 (> 150), rising → alert
        assert evaluate_trend(151, "FortyFiveUp", TREND_CONFIG) == "rising"

    def test_no_alert_when_glucose_below_high_warn_and_rising(self):
        # glucose 140 rising (not above threshold) → normal
        assert evaluate_trend(140, "↗", TREND_CONFIG) == "normal"

    def test_stable_trend_is_normal(self):
        # glucose 120, stable → normal
        assert evaluate_trend(120, "→", TREND_CONFIG) == "normal"

    def test_stable_trend_with_flat_text(self):
        assert evaluate_trend(120, "Flat", TREND_CONFIG) == "normal"

    def test_already_high_glucose_rising(self):
        # glucose 200 (> 150), rising → alert even though already high
        assert evaluate_trend(200, "↗", TREND_CONFIG) == "rising"

    def test_trend_disabled_returns_normal(self):
        # Trend config disabled → always normal
        assert evaluate_trend(95, "↓", TREND_DISABLED_CONFIG) == "normal"

    def test_no_trend_section_returns_normal(self):
        # No trend key in config → disabled by default
        assert evaluate_trend(95, "↓", NO_TREND_CONFIG) == "normal"


# ── should_alert with trend_alert ──────────────────────────────────────────

class TestShouldAlertWithTrend:
    def test_normal_level_trend_normal_returns_false(self):
        assert should_alert("normal", {}, cooldown_minutes=20, trend_alert="normal") is False

    def test_normal_level_falling_fast_triggers_alert(self):
        assert should_alert("normal", {}, cooldown_minutes=20, trend_alert="falling_fast") is True

    def test_normal_level_falling_triggers_alert(self):
        assert should_alert("normal", {}, cooldown_minutes=20, trend_alert="falling") is True

    def test_normal_level_rising_fast_triggers_alert(self):
        assert should_alert("normal", {}, cooldown_minutes=20, trend_alert="rising_fast") is True

    def test_low_level_overrides_trend(self):
        assert should_alert("low", {}, cooldown_minutes=20, trend_alert="normal") is True

    def test_trend_alert_cooldown_suppresses(self):
        state = {
            "last_alert_time": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
            "last_alert_level": "trend_falling_fast",
        }
        assert should_alert("normal", state, cooldown_minutes=20, trend_alert="falling_fast") is False

    def test_trend_alert_cooldown_expired_triggers(self):
        state = {
            "last_alert_time": (datetime.now(timezone.utc) - timedelta(minutes=25)).isoformat(),
            "last_alert_level": "trend_falling_fast",
        }
        assert should_alert("normal", state, cooldown_minutes=20, trend_alert="falling_fast") is True

    def test_trend_change_triggers_new_alert(self):
        state = {
            "last_alert_time": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
            "last_alert_level": "trend_falling",
        }
        # Changed from falling to falling_fast → new alert
        assert should_alert("normal", state, cooldown_minutes=20, trend_alert="falling_fast") is True

    def test_level_alert_takes_precedence_over_trend(self):
        # level=high should be tracked as "high", not trend prefix
        assert should_alert("high", {}, cooldown_minutes=20, trend_alert="rising_fast") is True


# ── build_message with trend_alert ─────────────────────────────────────────

class TestBuildMessageWithTrend:
    def test_low_level_ignores_trend_alert(self):
        msg = build_message(55, "low", "↓", "Mamá", trend_alert="falling_fast")
        assert "BAJA" in msg
        assert "Mamá" in msg

    def test_high_level_ignores_trend_alert(self):
        msg = build_message(200, "high", "↑", "Papá", trend_alert="rising_fast")
        assert "ALTA" in msg

    def test_trend_falling_fast_message(self):
        msg = build_message(95, "normal", "↓", "Ana", trend_alert="falling_fast")
        assert "Ana" in msg
        assert "95" in msg
        assert "BAJANDO" in msg.upper() or "bajando" in msg.lower()

    def test_trend_falling_message(self):
        msg = build_message(85, "normal", "↘", "Juan", trend_alert="falling")
        assert "Juan" in msg
        assert "85" in msg
        assert "hipo" in msg.lower() or "bajando" in msg.lower()

    def test_trend_rising_fast_message(self):
        msg = build_message(160, "normal", "↑", "Luis", trend_alert="rising_fast")
        assert "Luis" in msg
        assert "SUBIENDO" in msg.upper() or "subiendo" in msg.lower()

    def test_trend_rising_message(self):
        msg = build_message(155, "normal", "↗", "María", trend_alert="rising")
        assert "María" in msg
        assert "subiendo" in msg.lower() or "hiper" in msg.lower()

    def test_custom_trend_template_in_config(self):
        # Primary schema: alerts.trend.messages
        config = {
            "alerts": {
                "trend": {
                    "messages": {
                        "falling_fast": "PELIGRO {patient_name} bajando: {value}",
                    }
                }
            }
        }
        msg = build_message(90, "normal", "↓", "Test", config=config, trend_alert="falling_fast")
        assert msg == "PELIGRO Test bajando: 90"

    def test_custom_config_missing_trend_type_falls_back_to_default(self):
        # Config has a trend section but not the specific alert type → use default template
        config = {
            "alerts": {
                "trend": {
                    "messages": {
                        "rising_fast": "Subiendo rápido {patient_name}",
                        # "falling" is NOT defined here
                    }
                }
            }
        }
        msg = build_message(85, "normal", "↘", "Juan", config=config, trend_alert="falling")
        # Should fall back to built-in default and contain key info
        assert "Juan" in msg
        assert "85" in msg

    def test_backward_compat_alerts_messages_trend_path(self):
        # Backward compat: alerts.messages.trend still works as a fallback
        config = {
            "alerts": {
                "messages": {
                    "trend": {
                        "falling_fast": "COMPAT {patient_name} bajando: {value}",
                    }
                }
            }
        }
        msg = build_message(90, "normal", "↓", "Test", config=config, trend_alert="falling_fast")
        assert msg == "COMPAT Test bajando: 90"

    def test_primary_path_takes_precedence_over_fallback(self):
        # When both paths are present, alerts.trend.messages takes precedence
        config = {
            "alerts": {
                "trend": {
                    "messages": {
                        "falling_fast": "PRIMARY {patient_name}: {value}",
                    }
                },
                "messages": {
                    "trend": {
                        "falling_fast": "FALLBACK {patient_name}: {value}",
                    }
                },
            }
        }
        msg = build_message(90, "normal", "↓", "Test", config=config, trend_alert="falling_fast")
        assert msg == "PRIMARY Test: 90"

    def test_backward_compat_no_trend_alert_arg(self):
        # Original signature without trend_alert should still work
        msg = build_message(55, "low", "↓", "Mamá")
        assert "BAJA" in msg
