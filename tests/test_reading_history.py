"""Unit tests for src/reading_history.py."""
from datetime import datetime, timedelta, timezone

import pytest

from src import reading_history


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def db_path(tmp_path):
    """Return a fresh temporary reading_history.db path."""
    path = str(tmp_path / "reading_history.db")
    reading_history.init_db(path)
    # Clear the engine cache so each test gets a fresh engine for the temp path
    reading_history._engines.pop(path, None)
    reading_history.init_db(path)
    return path


# ── init_db ───────────────────────────────────────────────────────────────────

class TestInitDb:
    def test_creates_file(self, tmp_path):
        path = str(tmp_path / "new.db")
        reading_history.init_db(path)
        assert (tmp_path / "new.db").exists()

    def test_idempotent(self, db_path):
        """Calling init_db a second time must not raise."""
        reading_history.init_db(db_path)

    def test_creates_parent_dirs(self, tmp_path):
        path = str(tmp_path / "nested" / "dir" / "reading_history.db")
        reading_history.init_db(path)
        assert (tmp_path / "nested" / "dir" / "reading_history.db").exists()


# ── log_reading / get_readings ────────────────────────────────────────────────

class TestLogAndGetReadings:
    def test_returns_empty_before_any_logs(self, db_path):
        result = reading_history.get_readings(db_path, "p1", hours=3)
        assert result == []

    def test_logs_and_retrieves_one_reading(self, db_path):
        reading_history.log_reading(db_path, "p1", "Ana", 120)
        result = reading_history.get_readings(db_path, "p1", hours=3)
        assert len(result) == 1
        assert result[0]["patient_id"] == "p1"
        assert result[0]["patient_name"] == "Ana"
        assert result[0]["glucose_value"] == 120

    def test_logs_multiple_readings(self, db_path):
        for g in [100, 110, 120]:
            reading_history.log_reading(db_path, "p1", "Ana", g)
        result = reading_history.get_readings(db_path, "p1", hours=3)
        assert len(result) == 3
        assert [r["glucose_value"] for r in result] == [100, 110, 120]

    def test_filters_by_patient_id(self, db_path):
        reading_history.log_reading(db_path, "p1", "Ana", 110)
        reading_history.log_reading(db_path, "p2", "Juan", 130)
        result = reading_history.get_readings(db_path, "p1", hours=3)
        assert all(r["patient_id"] == "p1" for r in result)
        assert len(result) == 1

    def test_results_ordered_oldest_first(self, db_path):
        """get_readings returns ascending time order."""
        reading_history.log_reading(db_path, "p1", "Ana", 100)
        reading_history.log_reading(db_path, "p1", "Ana", 150)
        result = reading_history.get_readings(db_path, "p1", hours=3)
        # Timestamps are ISO strings; ascending order means earlier < later
        assert result[0]["glucose_value"] == 100
        assert result[1]["glucose_value"] == 150

    def test_hours_window_excludes_old_readings(self, db_path):
        """Readings outside the time window should not be returned."""
        engine = reading_history._get_engine(db_path)
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat()
        # Insert an old reading directly via SQLAlchemy
        from src.models.db_models import ReadingHistory
        from sqlalchemy.orm import Session
        with Session(engine) as session:
            session.add(ReadingHistory(
                timestamp=old_ts,
                patient_id="p1",
                patient_name="Ana",
                glucose_value=80,
            ))
            session.commit()
        # Should not appear in a 3-hour window
        result = reading_history.get_readings(db_path, "p1", hours=3)
        assert len(result) == 0

    def test_hours_window_includes_recent_readings(self, db_path):
        reading_history.log_reading(db_path, "p1", "Ana", 110)
        result = reading_history.get_readings(db_path, "p1", hours=3)
        assert len(result) == 1

    def test_returns_empty_when_db_missing(self, tmp_path):
        path = str(tmp_path / "nonexistent.db")
        result = reading_history.get_readings(path, "p1", hours=3)
        assert result == []

    def test_result_dict_has_required_keys(self, db_path):
        reading_history.log_reading(db_path, "p1", "Ana", 115)
        result = reading_history.get_readings(db_path, "p1", hours=3)
        assert set(result[0].keys()) >= {"timestamp", "patient_id", "patient_name", "glucose_value"}


# ── cleanup_old_readings ──────────────────────────────────────────────────────

class TestCleanupOldReadings:
    def test_returns_zero_when_db_missing(self, tmp_path):
        path = str(tmp_path / "nonexistent.db")
        deleted = reading_history.cleanup_old_readings(path, max_days=3)
        assert deleted == 0

    def test_deletes_old_readings(self, db_path):
        engine = reading_history._get_engine(db_path)
        old_ts = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        from src.models.db_models import ReadingHistory
        from sqlalchemy.orm import Session
        with Session(engine) as session:
            session.add(ReadingHistory(
                timestamp=old_ts,
                patient_id="p1",
                patient_name="Ana",
                glucose_value=90,
            ))
            session.commit()
        deleted = reading_history.cleanup_old_readings(db_path, max_days=3)
        assert deleted == 1

    def test_keeps_recent_readings(self, db_path):
        reading_history.log_reading(db_path, "p1", "Ana", 100)
        deleted = reading_history.cleanup_old_readings(db_path, max_days=3)
        assert deleted == 0
        result = reading_history.get_readings(db_path, "p1", hours=48)
        assert len(result) == 1
