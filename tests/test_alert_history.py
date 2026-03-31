"""Tests for the alert_history module."""
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.alert_history import cleanup_old_alerts, get_alerts, init_db, log_alert


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _db(tmp_path: Path) -> str:
    return str(tmp_path / "test_alerts.db")


def _ts(delta: timedelta = timedelta()) -> str:
    """Return a UTC ISO-8601 timestamp offset by *delta* from now."""
    return (datetime.now(timezone.utc) + delta).isoformat()


def _insert(db_path: str, patient_id: str = "p1", patient_name: str = "Patient",
            glucose_value: int = 55, level: str = "low",
            trend_arrow: str = "↓", message: str = "test msg",
            timestamp: str | None = None) -> None:
    ts = timestamp or _ts()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO alerts "
            "(timestamp, patient_id, patient_name, glucose_value, level, trend_arrow, message) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ts, patient_id, patient_name, glucose_value, level, trend_arrow, message),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# init_db
# ---------------------------------------------------------------------------

def test_init_db_creates_table(tmp_path):
    db = _db(tmp_path)
    init_db(db)

    with sqlite3.connect(db) as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='alerts'"
        ).fetchone()
    assert row is not None, "alerts table should exist after init_db"


def test_init_db_idempotent(tmp_path):
    """Calling init_db twice should not raise."""
    db = _db(tmp_path)
    init_db(db)
    init_db(db)  # should not raise


def test_init_db_creates_parent_dirs(tmp_path):
    db = str(tmp_path / "nested" / "dir" / "alerts.db")
    init_db(db)
    assert Path(db).exists()


# ---------------------------------------------------------------------------
# log_alert
# ---------------------------------------------------------------------------

def test_log_alert_inserts_row(tmp_path):
    db = _db(tmp_path)
    init_db(db)

    log_alert(db, "p1", "María", 55, "low", "↓", "test message")

    with sqlite3.connect(db) as conn:
        rows = conn.execute("SELECT * FROM alerts").fetchall()
    assert len(rows) == 1
    row = rows[0]
    assert row[2] == "p1"         # patient_id
    assert row[3] == "María"      # patient_name
    assert row[4] == 55           # glucose_value
    assert row[5] == "low"        # level
    assert row[6] == "↓"          # trend_arrow
    assert row[7] == "test message"  # message


def test_log_alert_multiple_rows(tmp_path):
    db = _db(tmp_path)
    init_db(db)

    log_alert(db, "p1", "María", 55, "low", "↓", "msg1")
    log_alert(db, "p2", "Juan", 200, "high", "↑", "msg2")

    with sqlite3.connect(db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
    assert count == 2


def test_log_alert_timestamp_is_utc_iso(tmp_path):
    db = _db(tmp_path)
    init_db(db)
    log_alert(db, "p1", "María", 55, "low", "↓", "msg")

    with sqlite3.connect(db) as conn:
        ts = conn.execute("SELECT timestamp FROM alerts").fetchone()[0]

    # Should parse without error and have timezone info
    parsed = datetime.fromisoformat(ts)
    assert parsed.tzinfo is not None


# ---------------------------------------------------------------------------
# get_alerts
# ---------------------------------------------------------------------------

def test_get_alerts_returns_empty_if_no_db(tmp_path):
    db = str(tmp_path / "nonexistent.db")
    result = get_alerts(db)
    assert result == []


def test_get_alerts_returns_recent_rows(tmp_path):
    db = _db(tmp_path)
    init_db(db)
    _insert(db, timestamp=_ts(timedelta(hours=-1)))
    _insert(db, timestamp=_ts(timedelta(hours=-23)))

    result = get_alerts(db, hours=24)
    assert len(result) == 2


def test_get_alerts_excludes_old_rows(tmp_path):
    db = _db(tmp_path)
    init_db(db)
    _insert(db, timestamp=_ts(timedelta(hours=-25)))  # older than 24h

    result = get_alerts(db, hours=24)
    assert result == []


def test_get_alerts_filters_by_patient_id(tmp_path):
    db = _db(tmp_path)
    init_db(db)
    _insert(db, patient_id="p1")
    _insert(db, patient_id="p2")

    result = get_alerts(db, patient_id="p1")
    assert len(result) == 1
    assert result[0]["patient_id"] == "p1"


def test_get_alerts_returns_all_patients_when_no_filter(tmp_path):
    db = _db(tmp_path)
    init_db(db)
    _insert(db, patient_id="p1")
    _insert(db, patient_id="p2")

    result = get_alerts(db)
    assert len(result) == 2


def test_get_alerts_returns_dicts_with_expected_keys(tmp_path):
    db = _db(tmp_path)
    init_db(db)
    _insert(db)

    result = get_alerts(db)
    assert len(result) == 1
    row = result[0]
    for key in ("id", "timestamp", "patient_id", "patient_name",
                "glucose_value", "level", "trend_arrow", "message"):
        assert key in row, f"Key '{key}' missing from result dict"


def test_get_alerts_ordered_most_recent_first(tmp_path):
    db = _db(tmp_path)
    init_db(db)
    _insert(db, timestamp=_ts(timedelta(hours=-3)))
    _insert(db, timestamp=_ts(timedelta(hours=-1)))

    result = get_alerts(db)
    assert result[0]["timestamp"] > result[1]["timestamp"]


def test_get_alerts_custom_hours(tmp_path):
    db = _db(tmp_path)
    init_db(db)
    _insert(db, timestamp=_ts(timedelta(hours=-2)))   # within 3h
    _insert(db, timestamp=_ts(timedelta(hours=-4)))   # outside 3h

    result = get_alerts(db, hours=3)
    assert len(result) == 1


# ---------------------------------------------------------------------------
# cleanup_old_alerts
# ---------------------------------------------------------------------------

def test_cleanup_returns_zero_if_no_db(tmp_path):
    db = str(tmp_path / "nonexistent.db")
    assert cleanup_old_alerts(db) == 0


def test_cleanup_removes_old_rows(tmp_path):
    db = _db(tmp_path)
    init_db(db)
    _insert(db, timestamp=_ts(timedelta(days=-8)))   # older than 7 days
    _insert(db, timestamp=_ts(timedelta(days=-1)))   # recent

    deleted = cleanup_old_alerts(db, max_days=7)
    assert deleted == 1

    with sqlite3.connect(db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
    assert count == 1


def test_cleanup_keeps_recent_rows(tmp_path):
    db = _db(tmp_path)
    init_db(db)
    _insert(db, timestamp=_ts(timedelta(hours=-1)))
    _insert(db, timestamp=_ts(timedelta(days=-3)))

    deleted = cleanup_old_alerts(db, max_days=7)
    assert deleted == 0


def test_cleanup_returns_count_of_deleted_rows(tmp_path):
    db = _db(tmp_path)
    init_db(db)
    _insert(db, timestamp=_ts(timedelta(days=-10)))
    _insert(db, timestamp=_ts(timedelta(days=-9)))
    _insert(db, timestamp=_ts(timedelta(hours=-1)))

    deleted = cleanup_old_alerts(db, max_days=7)
    assert deleted == 2


def test_cleanup_custom_max_days(tmp_path):
    db = _db(tmp_path)
    init_db(db)
    _insert(db, timestamp=_ts(timedelta(days=-2)))   # older than 1 day
    _insert(db, timestamp=_ts(timedelta(hours=-1)))  # recent

    deleted = cleanup_old_alerts(db, max_days=1)
    assert deleted == 1
