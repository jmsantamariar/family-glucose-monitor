"""Tests for run_once() in src.main."""
import copy
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, call, patch

import pytest

from src.main import run_once

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_CONFIG = {
    "librelinkup": {"email": "user@example.com", "password": "secret"},
    "alerts": {
        "low_threshold": 70,
        "high_threshold": 180,
        "cooldown_minutes": 20,
        "max_reading_age_minutes": 15,
    },
    "outputs": [],
    "state_file": "/tmp/run_once_test_state.json",
    "alert_history_db": "/tmp/run_once_test_history.db",
}


def _config(**overrides):
    cfg = copy.deepcopy(_BASE_CONFIG)
    cfg.update(overrides)
    return cfg


def _fresh_reading(glucose=150, patient_id="p1", patient_name="John Doe",
                   trend_arrow="→", age_seconds=0):
    """Return a reading dict with a fresh (non-stale) timestamp by default."""
    ts = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    return {
        "patient_id": patient_id,
        "patient_name": patient_name,
        "value": glucose,
        "timestamp": ts,
        "trend_name": "Flat",
        "trend_arrow": trend_arrow,
        "is_high": glucose > 180,
        "is_low": glucose < 70,
    }


def _stale_reading(**kwargs):
    """Return a reading that is clearly older than max_reading_age_minutes."""
    return _fresh_reading(age_seconds=3600, **kwargs)  # 1 hour old


class _MockOutput:
    """Minimal output mock that records calls."""

    def __init__(self, success=True):
        self._success = success
        self.send_alert = MagicMock(return_value=self._success)


# ---------------------------------------------------------------------------
# No readings obtained
# ---------------------------------------------------------------------------

def test_no_readings_returns_early():
    """run_once returns early and does not save state when no readings arrive."""
    with (
        patch("src.main.init_db"),
        patch("src.main.load_state", return_value={}),
        patch("src.main.save_state") as mock_save,
        patch("src.main.read_all_patients", return_value=[]),
        patch("src.main._save_readings_cache") as mock_cache,
        patch("src.main.cleanup_old_alerts"),
    ):
        run_once(_config())

    mock_cache.assert_not_called()
    mock_save.assert_not_called()


# ---------------------------------------------------------------------------
# Stale readings are skipped
# ---------------------------------------------------------------------------

def test_stale_reading_is_skipped():
    """A stale reading does not trigger an alert or state change."""
    reading = _stale_reading(glucose=50)  # low but stale

    mock_output = _MockOutput(success=True)

    with (
        patch("src.main.init_db"),
        patch("src.main.load_state", return_value={}),
        patch("src.main.save_state") as mock_save,
        patch("src.main.read_all_patients", return_value=[reading]),
        patch("src.main._save_readings_cache"),
        patch("src.main.log_alert") as mock_log,
        patch("src.main.cleanup_old_alerts"),
        patch("src.main.build_outputs", return_value=[mock_output]),
    ):
        run_once(_config())

    mock_output.send_alert.assert_not_called()
    mock_log.assert_not_called()
    mock_save.assert_not_called()


def test_stale_reading_does_not_clear_existing_state():
    """A stale reading for a patient in alert state does not clear that state."""
    reading = _stale_reading(glucose=50, patient_id="p1")
    existing_state = {
        "p1": {
            "last_alert_time": datetime.now(timezone.utc).isoformat(),
            "last_alert_level": "low",
        }
    }

    with (
        patch("src.main.init_db"),
        patch("src.main.load_state", return_value=copy.deepcopy(existing_state)),
        patch("src.main.save_state") as mock_save,
        patch("src.main.read_all_patients", return_value=[reading]),
        patch("src.main._save_readings_cache"),
        patch("src.main.log_alert"),
        patch("src.main.cleanup_old_alerts"),
    ):
        run_once(_config())

    mock_save.assert_not_called()


# ---------------------------------------------------------------------------
# Normal readings clear existing patient state
# ---------------------------------------------------------------------------

def test_normal_reading_clears_previous_alert_state():
    """A normal reading for a patient in alert state clears state and saves."""
    reading = _fresh_reading(glucose=120, patient_id="p1")  # normal range
    existing_state = {
        "p1": {
            "last_alert_time": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
            "last_alert_level": "low",
        }
    }

    with (
        patch("src.main.init_db"),
        patch("src.main.load_state", return_value=copy.deepcopy(existing_state)),
        patch("src.main.save_state") as mock_save,
        patch("src.main.read_all_patients", return_value=[reading]),
        patch("src.main._save_readings_cache"),
        patch("src.main.log_alert") as mock_log,
        patch("src.main.cleanup_old_alerts"),
    ):
        run_once(_config())

    mock_log.assert_not_called()
    mock_save.assert_called_once()


def test_normal_reading_no_previous_state_does_not_save():
    """A normal reading for a patient with no previous state does not trigger a save."""
    reading = _fresh_reading(glucose=120, patient_id="p1")

    with (
        patch("src.main.init_db"),
        patch("src.main.load_state", return_value={}),
        patch("src.main.save_state") as mock_save,
        patch("src.main.read_all_patients", return_value=[reading]),
        patch("src.main._save_readings_cache"),
        patch("src.main.log_alert") as mock_log,
        patch("src.main.cleanup_old_alerts"),
    ):
        run_once(_config())

    mock_log.assert_not_called()
    mock_save.assert_not_called()


# ---------------------------------------------------------------------------
# Alert is sent when thresholds are breached
# ---------------------------------------------------------------------------

def test_low_glucose_triggers_alert():
    """A glucose value below the low threshold sends an alert."""
    reading = _fresh_reading(glucose=55, patient_id="p1")  # below low_threshold=70

    mock_output = _MockOutput(success=True)

    with (
        patch("src.main.init_db"),
        patch("src.main.load_state", return_value={}),
        patch("src.main.save_state") as mock_save,
        patch("src.main.read_all_patients", return_value=[reading]),
        patch("src.main._save_readings_cache"),
        patch("src.main.log_alert") as mock_log,
        patch("src.main.cleanup_old_alerts"),
        patch("src.main.build_outputs", return_value=[mock_output]),
    ):
        run_once(_config())

    mock_output.send_alert.assert_called_once()
    mock_log.assert_called_once()
    mock_save.assert_called_once()


def test_high_glucose_triggers_alert():
    """A glucose value above the high threshold sends an alert."""
    reading = _fresh_reading(glucose=220, patient_id="p1")  # above high_threshold=180

    mock_output = _MockOutput(success=True)

    with (
        patch("src.main.init_db"),
        patch("src.main.load_state", return_value={}),
        patch("src.main.save_state") as mock_save,
        patch("src.main.read_all_patients", return_value=[reading]),
        patch("src.main._save_readings_cache"),
        patch("src.main.log_alert") as mock_log,
        patch("src.main.cleanup_old_alerts"),
        patch("src.main.build_outputs", return_value=[mock_output]),
    ):
        run_once(_config())

    mock_output.send_alert.assert_called_once()
    mock_log.assert_called_once()
    mock_save.assert_called_once()


def test_alert_updates_patient_state():
    """A successful alert updates patient state with the correct level."""
    reading = _fresh_reading(glucose=55, patient_id="p1")

    mock_output = _MockOutput(success=True)

    saved_state = {}

    def capture_save(path, state):
        saved_state.update(state)

    with (
        patch("src.main.init_db"),
        patch("src.main.load_state", return_value={}),
        patch("src.main.save_state", side_effect=capture_save),
        patch("src.main.read_all_patients", return_value=[reading]),
        patch("src.main._save_readings_cache"),
        patch("src.main.log_alert"),
        patch("src.main.cleanup_old_alerts"),
        patch("src.main.build_outputs", return_value=[mock_output]),
    ):
        run_once(_config())

    assert "p1" in saved_state
    assert saved_state["p1"]["last_alert_level"] == "low"
    assert "last_alert_time" in saved_state["p1"]


def test_alert_logs_to_history():
    """A successful alert is logged to the alert history database."""
    reading = _fresh_reading(glucose=55, patient_id="p1", patient_name="Alice")

    mock_output = _MockOutput(success=True)

    with (
        patch("src.main.init_db"),
        patch("src.main.load_state", return_value={}),
        patch("src.main.save_state"),
        patch("src.main.read_all_patients", return_value=[reading]),
        patch("src.main._save_readings_cache"),
        patch("src.main.log_alert") as mock_log,
        patch("src.main.cleanup_old_alerts"),
        patch("src.main.build_outputs", return_value=[mock_output]),
    ):
        run_once(_config())

    mock_log.assert_called_once()
    args = mock_log.call_args[0]
    assert args[1] == "p1"          # patient_id
    assert args[2] == "Alice"       # patient_name
    assert args[3] == 55            # glucose_value
    assert args[4] == "low"         # level


# ---------------------------------------------------------------------------
# Cooldown suppresses repeated alerts
# ---------------------------------------------------------------------------

def test_cooldown_suppresses_repeated_alert():
    """An alert is suppressed when within the cooldown window."""
    reading = _fresh_reading(glucose=55, patient_id="p1")
    recent_alert_time = datetime.now(timezone.utc).isoformat()
    existing_state = {
        "p1": {
            "last_alert_time": recent_alert_time,
            "last_alert_level": "low",
        }
    }

    mock_output = _MockOutput(success=True)

    with (
        patch("src.main.init_db"),
        patch("src.main.load_state", return_value=copy.deepcopy(existing_state)),
        patch("src.main.save_state") as mock_save,
        patch("src.main.read_all_patients", return_value=[reading]),
        patch("src.main._save_readings_cache"),
        patch("src.main.log_alert") as mock_log,
        patch("src.main.cleanup_old_alerts"),
        patch("src.main.build_outputs", return_value=[mock_output]),
    ):
        run_once(_config())

    mock_output.send_alert.assert_not_called()
    mock_log.assert_not_called()
    mock_save.assert_not_called()


def test_alert_fires_after_cooldown_expires():
    """An alert is sent when the cooldown period has elapsed."""
    reading = _fresh_reading(glucose=55, patient_id="p1")
    # Last alert was 30 minutes ago; cooldown is 20 minutes
    old_alert_time = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    existing_state = {
        "p1": {
            "last_alert_time": old_alert_time,
            "last_alert_level": "low",
        }
    }

    mock_output = _MockOutput(success=True)

    with (
        patch("src.main.init_db"),
        patch("src.main.load_state", return_value=copy.deepcopy(existing_state)),
        patch("src.main.save_state") as mock_save,
        patch("src.main.read_all_patients", return_value=[reading]),
        patch("src.main._save_readings_cache"),
        patch("src.main.log_alert") as mock_log,
        patch("src.main.cleanup_old_alerts"),
        patch("src.main.build_outputs", return_value=[mock_output]),
    ):
        run_once(_config())

    mock_output.send_alert.assert_called_once()
    mock_log.assert_called_once()
    mock_save.assert_called_once()


# ---------------------------------------------------------------------------
# All outputs fail — state must NOT be updated
# ---------------------------------------------------------------------------

def test_all_outputs_fail_state_not_updated():
    """When all outputs fail, state is not saved and no alert is logged."""
    reading = _fresh_reading(glucose=55, patient_id="p1")

    mock_output = _MockOutput(success=False)

    with (
        patch("src.main.init_db"),
        patch("src.main.load_state", return_value={}),
        patch("src.main.save_state") as mock_save,
        patch("src.main.read_all_patients", return_value=[reading]),
        patch("src.main._save_readings_cache"),
        patch("src.main.log_alert") as mock_log,
        patch("src.main.cleanup_old_alerts"),
        patch("src.main.build_outputs", return_value=[mock_output]),
    ):
        run_once(_config())

    mock_output.send_alert.assert_called_once()
    mock_log.assert_not_called()
    mock_save.assert_not_called()


def test_partial_output_success_updates_state():
    """If at least one output succeeds, state is updated even if others fail."""
    reading = _fresh_reading(glucose=55, patient_id="p1")

    mock_fail = _MockOutput(success=False)
    mock_ok = _MockOutput(success=True)

    with (
        patch("src.main.init_db"),
        patch("src.main.load_state", return_value={}),
        patch("src.main.save_state") as mock_save,
        patch("src.main.read_all_patients", return_value=[reading]),
        patch("src.main._save_readings_cache"),
        patch("src.main.log_alert") as mock_log,
        patch("src.main.cleanup_old_alerts"),
        patch("src.main.build_outputs", return_value=[mock_fail, mock_ok]),
    ):
        run_once(_config())

    mock_log.assert_called_once()
    mock_save.assert_called_once()


def test_output_exception_treated_as_failure():
    """An exception raised by an output is treated as a failure."""
    reading = _fresh_reading(glucose=55, patient_id="p1")

    mock_output = MagicMock()
    mock_output.send_alert.side_effect = Exception("connection error")

    with (
        patch("src.main.init_db"),
        patch("src.main.load_state", return_value={}),
        patch("src.main.save_state") as mock_save,
        patch("src.main.read_all_patients", return_value=[reading]),
        patch("src.main._save_readings_cache"),
        patch("src.main.log_alert") as mock_log,
        patch("src.main.cleanup_old_alerts"),
        patch("src.main.build_outputs", return_value=[mock_output]),
    ):
        run_once(_config())

    mock_log.assert_not_called()
    mock_save.assert_not_called()


# ---------------------------------------------------------------------------
# Readings cache save
# ---------------------------------------------------------------------------

def test_save_readings_cache_is_called_with_readings():
    """_save_readings_cache is called with the received readings."""
    reading = _fresh_reading(glucose=120)

    with (
        patch("src.main.init_db"),
        patch("src.main.load_state", return_value={}),
        patch("src.main.save_state"),
        patch("src.main.read_all_patients", return_value=[reading]),
        patch("src.main._save_readings_cache") as mock_cache,
        patch("src.main.log_alert"),
        patch("src.main.cleanup_old_alerts"),
    ):
        run_once(_config())

    mock_cache.assert_called_once()
    cache_args = mock_cache.call_args[0]
    assert cache_args[0] == [reading]  # first arg is the readings list


def test_save_readings_cache_not_called_when_no_readings():
    """_save_readings_cache is not called when read_all_patients returns empty."""
    with (
        patch("src.main.init_db"),
        patch("src.main.load_state", return_value={}),
        patch("src.main.save_state"),
        patch("src.main.read_all_patients", return_value=[]),
        patch("src.main._save_readings_cache") as mock_cache,
        patch("src.main.log_alert"),
        patch("src.main.cleanup_old_alerts"),
    ):
        run_once(_config())

    mock_cache.assert_not_called()


# ---------------------------------------------------------------------------
# Cleanup is always called
# ---------------------------------------------------------------------------

def test_cleanup_old_alerts_is_always_called():
    """cleanup_old_alerts is called even when there are no alerts to send."""
    reading = _fresh_reading(glucose=120)

    with (
        patch("src.main.init_db"),
        patch("src.main.load_state", return_value={}),
        patch("src.main.save_state"),
        patch("src.main.read_all_patients", return_value=[reading]),
        patch("src.main._save_readings_cache"),
        patch("src.main.log_alert"),
        patch("src.main.cleanup_old_alerts") as mock_cleanup,
    ):
        run_once(_config())

    mock_cleanup.assert_called_once()


def test_cleanup_uses_config_max_days():
    """cleanup_old_alerts receives max_days from config."""
    reading = _fresh_reading(glucose=120)
    cfg = _config(alert_history_max_days=14)

    with (
        patch("src.main.init_db"),
        patch("src.main.load_state", return_value={}),
        patch("src.main.save_state"),
        patch("src.main.read_all_patients", return_value=[reading]),
        patch("src.main._save_readings_cache"),
        patch("src.main.log_alert"),
        patch("src.main.cleanup_old_alerts") as mock_cleanup,
    ):
        run_once(cfg)

    # second positional arg is max_days
    assert mock_cleanup.call_args[0][1] == 14


# ---------------------------------------------------------------------------
# Multiple patients — independent processing
# ---------------------------------------------------------------------------

def test_multiple_patients_processed_independently():
    """One normal and one low patient — only the low one triggers an alert."""
    normal = _fresh_reading(glucose=120, patient_id="p1", patient_name="Alice")
    low = _fresh_reading(glucose=55, patient_id="p2", patient_name="Bob")

    mock_output = _MockOutput(success=True)

    with (
        patch("src.main.init_db"),
        patch("src.main.load_state", return_value={}),
        patch("src.main.save_state") as mock_save,
        patch("src.main.read_all_patients", return_value=[normal, low]),
        patch("src.main._save_readings_cache"),
        patch("src.main.log_alert") as mock_log,
        patch("src.main.cleanup_old_alerts"),
        patch("src.main.build_outputs", return_value=[mock_output]),
    ):
        run_once(_config())

    assert mock_output.send_alert.call_count == 1
    mock_log.assert_called_once()
    mock_save.assert_called_once()
    saved_state = mock_save.call_args[0][1]
    assert "p2" in saved_state
    assert saved_state.get("p1", {}) == {} or "p1" not in saved_state
