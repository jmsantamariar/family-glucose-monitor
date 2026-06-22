"""Stale readings must not be re-logged to reading_history on every poll.

When a patient's sensor goes silent, every poll cycle re-delivers the same
last reading. Logging it each time produces fake flat segments in the
dashboard charts and inflates n_readings/TIR/CV in the history metrics.
``log_reading_if_new`` deduplicates by the sensor's own timestamp.

The dedup now lives in src.reading_history (called by the polling daemon on
every cycle) rather than in the dashboard's cache-enrichment path, so the
history is captured continuously whether or not a client is connected.
"""
from unittest.mock import MagicMock

import pytest

import src.reading_history as rh


@pytest.fixture()
def log_spy(monkeypatch):
    """Spy on the underlying writer and reset the in-memory dedup state."""
    monkeypatch.setattr(rh, "_last_logged_source_ts", {})
    spy = MagicMock()
    monkeypatch.setattr(rh, "log_reading", spy)
    return spy


def _log(pid, value, ts):
    return rh.log_reading_if_new("unused.db", pid, f"Patient {pid}", value, ts)


def test_same_sensor_timestamp_logged_once(log_spy):
    ts = "2026-06-06 10:00:00+00:00"
    assert _log("p1", 110, ts) is True
    assert _log("p1", 110, ts) is False
    assert log_spy.call_count == 1


def test_new_sensor_timestamp_logged_again(log_spy):
    assert _log("p1", 110, "2026-06-06 10:00:00+00:00") is True
    assert _log("p1", 112, "2026-06-06 10:05:00+00:00") is True
    assert log_spy.call_count == 2


def test_dedup_is_per_patient(log_spy):
    ts = "2026-06-06 10:00:00+00:00"
    _log("p1", 110, ts)
    _log("p2", 95, ts)
    # p1 stale (same ts), p2 advanced
    _log("p1", 110, ts)
    _log("p2", 99, "2026-06-06 10:05:00+00:00")
    logged_pids = [c.args[1] for c in log_spy.call_args_list]
    assert logged_pids.count("p1") == 1
    assert logged_pids.count("p2") == 2


def test_missing_timestamp_still_logged(log_spy):
    """Readings without a sensor timestamp fall back to always logging —
    we prefer an occasional duplicate over silently dropping data."""
    assert _log("p1", 110, "") is True
    assert _log("p1", 110, "") is True
    assert log_spy.call_count == 2
