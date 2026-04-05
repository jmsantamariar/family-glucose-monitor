"""SQLAlchemy ORM models for family-glucose-monitor.

These models mirror the existing SQLite schemas and are used by
``src/alert_history.py`` and ``src/auth.py`` for all DML operations.
DDL (table/index creation) is still performed via raw SQL with
``IF NOT EXISTS`` guards so that existing databases are never altered.

Databases
---------
* ``sessions.db`` — ``sessions`` and ``login_attempts`` tables, managed by
  :mod:`src.auth`.
* ``alert_history.db`` — ``alerts`` table, managed by
  :mod:`src.alert_history`.

Physical table schemas (raw reference — not changed by this module):

``sessions`` (sessions.db)
  - token TEXT PRIMARY KEY
  - expires_at REAL NOT NULL

``login_attempts`` (sessions.db)
  - ip TEXT NOT NULL
  - timestamp REAL NOT NULL
  *(no primary key in the physical schema; accessed via SQLAlchemy text())*

``alerts`` (alert_history.db)
  - id INTEGER PRIMARY KEY AUTOINCREMENT
  - timestamp TEXT NOT NULL
  - patient_id TEXT NOT NULL
  - patient_name TEXT NOT NULL
  - glucose_value INTEGER NOT NULL
  - level TEXT NOT NULL
  - trend_arrow TEXT NOT NULL DEFAULT ''
  - message TEXT NOT NULL DEFAULT ''

``readings`` (reading_history.db)
  - id INTEGER PRIMARY KEY AUTOINCREMENT
  - timestamp TEXT NOT NULL
  - patient_id TEXT NOT NULL
  - patient_name TEXT NOT NULL
  - glucose_value INTEGER NOT NULL

TODO (Iteration 4 / ongoing):
  - Migrate ``login_attempts`` to full ORM once a PK column is added.
"""
from __future__ import annotations

from sqlalchemy import Column, Float, Index, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Session  # noqa: F401 – re-exported for callers


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


class SessionToken(Base):
    """Persistent session tokens for the dashboard web login.

    Mirrors the ``sessions`` table in ``sessions.db``.
    """

    __tablename__ = "sessions"
    __table_args__ = (
        # Match the index name created by the raw-SQL init in src/auth.py.
        Index("idx_sessions_expires", "expires_at"),
    )

    token = Column(String, primary_key=True, nullable=False)
    expires_at = Column(Float, nullable=False)

    def __repr__(self) -> str:
        return f"<SessionToken token=...{self.token[-8:]} expires_at={self.expires_at}>"


class LoginAttempt(Base):
    """Rate-limiting log of failed login attempts.

    Mirrors the ``login_attempts`` table in ``sessions.db``.

    .. note::
       The physical table has **no primary key**.  SQLAlchemy requires a PK
       for ORM-mapped classes, so a composite ``(ip, timestamp)`` PK is
       declared here for metadata purposes only.  All DML against this table
       is executed via ``session.execute(text(...))`` in :mod:`src.auth` to
       avoid PK-enforcement issues on rapid inserts.
    """

    __tablename__ = "login_attempts"
    __table_args__ = (
        # Match the composite index created by the raw-SQL init in src/auth.py.
        Index("idx_login_attempts_ip_ts", "ip", "timestamp"),
    )

    ip = Column(String, primary_key=True, nullable=False)
    timestamp = Column(Float, primary_key=True, nullable=False)

    def __repr__(self) -> str:
        return f"<LoginAttempt ip={self.ip!r} timestamp={self.timestamp}>"


class AlertHistory(Base):
    """Historical record of sent glucose alerts.

    Mirrors the ``alerts`` table in ``alert_history.db``.
    """

    __tablename__ = "alerts"
    __table_args__ = (
        # Match the index names created by the raw-SQL init in src/alert_history.py.
        Index("idx_alerts_timestamp", "timestamp"),
        Index("idx_alerts_patient_timestamp", "patient_id", "timestamp"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(Text, nullable=False)
    patient_id = Column(Text, nullable=False)
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


class ReadingHistory(Base):
    """Historical record of periodic glucose readings (sampled at each polling cycle).

    Mirrors the ``readings`` table in ``reading_history.db``.
    Used to power the mini sparkline in the expanded patient panel.
    """

    __tablename__ = "readings"
    __table_args__ = (
        Index("idx_readings_patient_ts", "patient_id", "timestamp"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(Text, nullable=False)
    patient_id = Column(Text, nullable=False)
    patient_name = Column(Text, nullable=False)
    glucose_value = Column(Integer, nullable=False)

    def __repr__(self) -> str:
        return (
            f"<ReadingHistory id={self.id} patient={self.patient_id!r} "
            f"glucose={self.glucose_value}>"
        )


def get_engine(db_url: str):
    """Return a SQLAlchemy engine for the given database URL.

    Uses ``check_same_thread=False`` for SQLite so the engine can be shared
    across threads (consistent with the existing raw-sqlite usage pattern),
    and applies a 10s SQLite busy timeout to match ``src.db.connect_db()``.
    """
    connect_args = {}
    if db_url.startswith("sqlite"):
        # Allow connections to be used across threads and mirror the 10s
        # busy timeout configured by the raw SQLite helper.
        connect_args["check_same_thread"] = False
        connect_args.setdefault("timeout", 10)
    return create_engine(db_url, connect_args=connect_args)


def create_tables(engine) -> None:
    """Create all ORM-mapped tables if they do not already exist.

    This is **non-destructive**: existing tables and their data are never
    altered or dropped.
    """
    Base.metadata.create_all(bind=engine, checkfirst=True)
