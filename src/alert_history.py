"""Persistent alert history using SQLite — accessed via SQLAlchemy ORM.

Stores a log of every alert sent so that patterns can be analysed
and visualised in the dashboard without relying on Telegram messages.

The public API (``init_db``, ``log_alert``, ``get_alerts``,
``cleanup_old_alerts``) is unchanged; all DML is now handled through
:class:`~src.models.db_models.AlertHistory` ORM sessions.

DDL (``CREATE TABLE / INDEX IF NOT EXISTS``) is still executed via raw SQL
so that existing database files are never altered.
"""
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from src.models.db_models import AlertHistory, get_engine

logger = logging.getLogger(__name__)

# Required columns in the ``alerts`` table (column name → SQLite type keyword).
_REQUIRED_COLUMNS: dict[str, str] = {
    "id": "INTEGER",
    "timestamp": "TEXT",
    "patient_id": "TEXT",
    "patient_name": "TEXT",
    "glucose_value": "INTEGER",
    "level": "TEXT",
    "trend_arrow": "TEXT",
    "message": "TEXT",
}


def validate_schema(db_path: str) -> list[str]:
    """Return a list of schema errors for an existing ``alert_history.db``.

    Returns an empty list when:
    * the database file does not exist yet (bootstrap will create it), or
    * the ``alerts`` table has all required columns.

    Each error string describes a missing required column, or reports that the
    ``alerts`` table itself is missing, so the caller can emit a clear,
    actionable message before failing.
    """
    db_file = Path(db_path)
    if not db_file.exists():
        return []

    errors: list[str] = []
    try:
        engine = _get_engine(db_path)
        with engine.connect() as conn:
            rows = conn.execute(text("PRAGMA table_info(alerts)")).fetchall()
        if not rows:
            errors.append(
                f"alerts table is missing in {db_path}; "
                "re-initialise the database or delete the file and restart."
            )
            return errors
        existing: dict[str, str] = {row[1]: row[2].upper() for row in rows}
        for col, expected_type in _REQUIRED_COLUMNS.items():
            if col not in existing:
                errors.append(
                    f"Column '{col}' ({expected_type}) is missing from the alerts table in {db_path}."
                )
    except Exception as exc:
        errors.append(f"Could not inspect schema of {db_path}: {exc}")
    return errors

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS alerts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT NOT NULL,
    patient_id    TEXT NOT NULL,
    patient_name  TEXT NOT NULL,
    glucose_value INTEGER NOT NULL,
    level         TEXT NOT NULL,
    trend_arrow   TEXT NOT NULL DEFAULT '',
    message       TEXT NOT NULL DEFAULT ''
);
"""

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_alerts_timestamp ON alerts(timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_alerts_patient_timestamp ON alerts(patient_id, timestamp);",
]

# Per-path engine cache: avoids creating a new engine on every call while
# still supporting multiple DB paths in tests.
_engines: dict[str, object] = {}


def _get_engine(db_path: str):
    """Return (and cache) a SQLAlchemy engine for *db_path*."""
    if db_path not in _engines:
        _engines[db_path] = get_engine(f"sqlite:///{db_path}")
    return _engines[db_path]


def init_db(db_path: str) -> None:
    """Create the alerts table and supporting indexes if they do not already exist."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    # Use raw SQL for DDL so the physical schema is never altered.
    from src.db import connect_db
    with connect_db(db_path) as conn:
        conn.execute(_CREATE_TABLE)
        for idx_sql in _CREATE_INDEXES:
            conn.execute(idx_sql)
        conn.commit()
    logger.debug("Alert history DB initialised at %s", db_path)


def log_alert(
    db_path: str,
    patient_id: str,
    patient_name: str,
    glucose_value: int,
    level: str,
    trend_arrow: str,
    message: str,
) -> None:
    """Record a successfully sent alert in the history database."""
    timestamp = datetime.now(timezone.utc).isoformat()
    engine = _get_engine(db_path)
    with Session(engine) as session:
        session.add(
            AlertHistory(
                timestamp=timestamp,
                patient_id=patient_id,
                patient_name=patient_name,
                glucose_value=int(glucose_value),
                level=level,
                trend_arrow=trend_arrow,
                message=message,
            )
        )
        session.commit()
    logger.debug("Alert logged for %s: %s %d mg/dL", patient_name, level, glucose_value)


def get_alerts(
    db_path: str,
    patient_id: str | None = None,
    hours: int = 24,
) -> list[dict]:
    """Return alerts from the last *hours* hours, optionally filtered by patient.

    Returns an empty list if the database does not exist yet.
    """
    if not Path(db_path).exists():
        return []

    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    engine = _get_engine(db_path)

    try:
        with Session(engine) as session:
            query = (
                select(AlertHistory)
                .where(AlertHistory.timestamp >= since)
                .order_by(AlertHistory.timestamp.desc())
            )
            if patient_id is not None:
                query = query.where(AlertHistory.patient_id == patient_id)
            rows = session.execute(query).scalars().all()
            return [
                {
                    "id": r.id,
                    "timestamp": r.timestamp,
                    "patient_id": r.patient_id,
                    "patient_name": r.patient_name,
                    "glucose_value": r.glucose_value,
                    "level": r.level,
                    "trend_arrow": r.trend_arrow,
                    "message": r.message,
                }
                for r in rows
            ]
    except Exception:
        # Table may not exist in an empty DB file
        return []


def cleanup_old_alerts(db_path: str, max_days: int = 7) -> int:
    """Delete alerts older than *max_days* days.

    Returns the number of rows deleted.
    """
    if not Path(db_path).exists():
        return 0

    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_days)).isoformat()
    engine = _get_engine(db_path)

    try:
        with Session(engine) as session:
            result = session.execute(
                delete(AlertHistory).where(AlertHistory.timestamp < cutoff)
            )
            session.commit()
            deleted = result.rowcount
    except Exception:
        return 0

    if deleted:
        logger.debug("Cleaned up %d old alert(s) from history", deleted)
    return deleted
