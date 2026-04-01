"""SQLAlchemy ORM models for family-glucose-monitor.

.. warning:: **This module is preparatory / Iteration 2.**

   The models defined here mirror the existing SQLite schema but are **not
   yet wired into the application**.  All live code still uses the raw
   ``sqlite3`` helpers in ``src/auth.py``, ``src/alert_history.py``, and
   ``src/db.py``.

   The intention is to introduce the ORM incrementally, table by table,
   in future iterations without breaking the existing schema.  Migration
   will be non-destructive: ``Base.metadata.create_all(bind=engine)`` only
   creates tables that do not already exist; it does not alter or drop
   existing ones.

Existing SQLite tables (raw schema reference):

``sessions`` (sessions.db)
  - token TEXT PRIMARY KEY
  - expires_at REAL NOT NULL

``login_attempts`` (sessions.db)
  - ip TEXT NOT NULL
  - timestamp REAL NOT NULL

``alerts`` (alert_history.db)
  - id INTEGER PRIMARY KEY AUTOINCREMENT
  - timestamp TEXT NOT NULL
  - patient_id TEXT NOT NULL
  - patient_name TEXT NOT NULL
  - glucose_value INTEGER NOT NULL
  - level TEXT NOT NULL
  - trend_arrow TEXT NOT NULL DEFAULT ''
  - message TEXT NOT NULL DEFAULT ''

TODO (Iteration 3):
  - Replace src/alert_history.py raw SQL with ORM calls.
  - Replace src/auth.py SessionManager with ORM-backed session management.
  - Add Alembic for schema migrations (non-destructive).
"""
from __future__ import annotations

from sqlalchemy import Column, Float, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Session


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


class SessionToken(Base):
    """Persistent session tokens for the dashboard web login.

    Mirrors the ``sessions`` table in ``sessions.db``.
    """

    __tablename__ = "sessions"

    token = Column(String, primary_key=True, nullable=False)
    expires_at = Column(Float, nullable=False, index=True)

    def __repr__(self) -> str:
        return f"<SessionToken token=...{self.token[-8:]} expires_at={self.expires_at}>"


class LoginAttempt(Base):
    """Rate-limiting log of failed login attempts.

    Mirrors the ``login_attempts`` table in ``sessions.db``.
    The table has no primary key in the raw schema; SQLAlchemy requires one,
    so we use a surrogate autoincrement id (non-destructive: added as a new
    column only if the table is freshly created via ORM).
    """

    __tablename__ = "login_attempts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ip = Column(String, nullable=False, index=True)
    timestamp = Column(Float, nullable=False, index=True)

    def __repr__(self) -> str:
        return f"<LoginAttempt ip={self.ip!r} timestamp={self.timestamp}>"


class AlertHistory(Base):
    """Historical record of sent glucose alerts.

    Mirrors the ``alerts`` table in ``alert_history.db``.
    """

    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(Text, nullable=False, index=True)
    patient_id = Column(Text, nullable=False, index=True)
    patient_name = Column(Text, nullable=False)
    glucose_value = Column(Integer, nullable=False)
    level = Column(Text, nullable=False)
    trend_arrow = Column(Text, nullable=False, default="")
    message = Column(Text, nullable=False, default="")

    def __repr__(self) -> str:
        return (
            f"<AlertHistory id={self.id} patient={self.patient_id!r} "
            f"level={self.level!r} glucose={self.glucose_value}>"
        )


def get_engine(db_url: str):
    """Return a SQLAlchemy engine for the given database URL.

    Uses ``check_same_thread=False`` for SQLite so the engine can be shared
    across threads (as in the existing raw-sqlite usage pattern).
    """
    connect_args = {}
    if db_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(db_url, connect_args=connect_args)


def create_tables(engine) -> None:
    """Create all ORM-mapped tables that do not already exist.

    This operation is **non-destructive**: existing tables and their data
    are never altered or dropped.
    """
    Base.metadata.create_all(bind=engine)
