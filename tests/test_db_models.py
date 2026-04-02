"""Tests for SQLAlchemy ORM models.

These tests verify that:
  - The ORM models can be imported and instantiated.
  - create_tables() creates the expected tables on a fresh in-memory SQLite DB.
  - The model attributes map correctly to column names.

The ORM is actively used by the application:
  - ``AlertHistory`` is used by ``src/alert_history.py`` for all DML.
  - ``SessionToken`` is used by ``src/auth.SessionManager`` for session DML.
  - ``LoginAttempt`` is described in the model but accessed via ``text()``
    queries in ``src/auth.SessionManager`` (no physical PK in the table).
"""
import pytest
from sqlalchemy import inspect, text

from src.models.db_models import (
    AlertHistory,
    LoginAttempt,
    SessionToken,
    create_tables,
    get_engine,
)


@pytest.fixture()
def engine():
    """Return a fresh in-memory SQLite engine for each test."""
    eng = get_engine("sqlite:///:memory:")
    create_tables(eng)
    return eng


# ---------------------------------------------------------------------------
# create_tables — schema smoke test
# ---------------------------------------------------------------------------

def test_create_tables_creates_sessions(engine):
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    assert "sessions" in tables


def test_create_tables_creates_login_attempts(engine):
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    assert "login_attempts" in tables


def test_create_tables_creates_alerts(engine):
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    assert "alerts" in tables


# ---------------------------------------------------------------------------
# create_tables — idempotent (calling twice must not raise)
# ---------------------------------------------------------------------------

def test_create_tables_is_idempotent(engine):
    create_tables(engine)  # second call — must not raise


# ---------------------------------------------------------------------------
# SessionToken
# ---------------------------------------------------------------------------

def test_session_token_repr():
    s = SessionToken(token="abc12345678", expires_at=9999.0)
    assert "12345678" in repr(s)
    assert "9999" in repr(s)


def test_session_token_columns():
    inspector = inspect(SessionToken)
    col_names = {c.key for c in inspector.mapper.column_attrs}
    assert "token" in col_names
    assert "expires_at" in col_names


# ---------------------------------------------------------------------------
# LoginAttempt
# ---------------------------------------------------------------------------

def test_login_attempt_repr():
    la = LoginAttempt(ip="127.0.0.1", timestamp=1000.0)
    assert "127.0.0.1" in repr(la)


def test_login_attempt_columns():
    inspector = inspect(LoginAttempt)
    col_names = {c.key for c in inspector.mapper.column_attrs}
    assert "ip" in col_names
    assert "timestamp" in col_names


# ---------------------------------------------------------------------------
# AlertHistory
# ---------------------------------------------------------------------------

def test_alert_history_repr():
    a = AlertHistory(
        patient_id="p1",
        patient_name="Alice",
        glucose_value=55,
        level="low",
        trend_arrow="↓",
        message="Low glucose",
        timestamp="2026-01-01T00:00:00",
    )
    assert "p1" in repr(a)
    assert "low" in repr(a)
    assert "55" in repr(a)


def test_alert_history_columns():
    inspector = inspect(AlertHistory)
    col_names = {c.key for c in inspector.mapper.column_attrs}
    expected = {
        "id",
        "timestamp",
        "patient_id",
        "patient_name",
        "glucose_value",
        "level",
        "trend_arrow",
        "message",
    }
    assert expected.issubset(col_names)


# ---------------------------------------------------------------------------
# get_engine — SQLite connect_args
# ---------------------------------------------------------------------------

def test_get_engine_sqlite_check_same_thread():
    eng = get_engine("sqlite:///:memory:")
    # Must not raise when called from a different thread
    with eng.connect() as conn:
        result = conn.execute(text("SELECT 1"))
        assert result.fetchone()[0] == 1
