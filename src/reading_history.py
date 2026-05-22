"""Persistent history of periodic glucose readings.

Stores a reading at each polling cycle (typically every ~5 minutes) so that
the dashboard can display a real time-series sparkline instead of synthetic
placeholder data.

The table is kept in a dedicated ``reading_history.db`` file (separate from
``alert_history.db``) to avoid polluting the alert log with routine readings.
Clean-up trims history older than ``max_days`` days (default 3) to avoid
unbounded disk growth.

Public API
----------
* :func:`init_db`         — create table/indexes (idempotent)
* :func:`log_reading`     — persist one glucose reading
* :func:`get_readings`    — retrieve readings for a patient within a time window
* :func:`cleanup_old_readings` — delete readings beyond the retention window
"""
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.db import connect_db
from src.models.db_models import ReadingHistory, get_engine

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS readings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT NOT NULL,
    patient_id    TEXT NOT NULL,
    patient_name  TEXT NOT NULL,
    glucose_value INTEGER NOT NULL
);
"""

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_readings_patient_ts ON readings(patient_id, timestamp);",
]

# Per-path engine cache — avoids creating a new engine on every call while
# still supporting multiple DB paths in tests.
_engines: dict[str, object] = {}


def _get_engine(db_path: str):
    """Return (and cache) a SQLAlchemy engine for *db_path*."""
    if db_path not in _engines:
        _engines[db_path] = get_engine(f"sqlite:///{db_path}")
    return _engines[db_path]


def init_db(db_path: str) -> None:
    """Create the readings table and supporting indexes if they do not already exist."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with connect_db(db_path) as conn:
        conn.execute(_CREATE_TABLE)
        for idx_sql in _CREATE_INDEXES:
            conn.execute(idx_sql)
        conn.commit()
    logger.debug("Reading history DB initialised at %s", db_path)


def log_reading(
    db_path: str,
    patient_id: str,
    patient_name: str,
    glucose_value: int,
) -> None:
    """Persist a single glucose reading for history tracking."""
    timestamp = datetime.now(timezone.utc).isoformat()
    engine = _get_engine(db_path)
    with Session(engine) as session:
        session.add(
            ReadingHistory(
                timestamp=timestamp,
                patient_id=patient_id,
                patient_name=patient_name,
                glucose_value=int(glucose_value),
            )
        )
        session.commit()
    logger.debug("Reading logged for patient %s: %d mg/dL", patient_id, glucose_value)


def get_readings(
    db_path: str,
    patient_id: str,
    hours: int = 3,
    days: int | None = None,
) -> list[dict]:
    """Return readings for *patient_id* in a recent time window.

    Window is specified by either ``hours`` (default 3) or ``days``. If
    ``days`` is provided, it overrides ``hours`` (converted internally).

    Results are ordered oldest-first so callers can iterate in time order.
    Returns an empty list if the database does not exist yet.

    Raises ValueError if the resulting window is non-positive.
    """
    if days is not None:
        if not isinstance(days, int) or days <= 0:
            raise ValueError(f"days must be a positive int, got {days!r}")
        hours = days * 24
    elif hours <= 0:
        raise ValueError(f"hours must be a positive int, got {hours!r}")

    if not Path(db_path).exists():
        return []

    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    engine = _get_engine(db_path)

    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT timestamp, patient_id, patient_name, glucose_value "
                    "FROM readings "
                    "WHERE patient_id = :pid AND timestamp >= :since "
                    "ORDER BY timestamp ASC"
                ),
                {"pid": patient_id, "since": since},
            ).fetchall()
        return [
            {
                "timestamp": row[0],
                "patient_id": row[1],
                "patient_name": row[2],
                "glucose_value": row[3],
            }
            for row in rows
        ]
    except Exception as exc:
        logger.warning("Failed to query reading history for patient %s: %s", patient_id, exc)
        return []


def downsample(readings: list[dict], bucket_seconds: int) -> list[dict]:
    """Bucket *readings* by ``bucket_seconds`` and return one synthetic row
    per bucket with the AVG of ``glucose_value`` and the bucket-start
    timestamp.

    Used to keep the response of ``/api/patients/{id}/history`` bounded
    for long ranges (a year of 5-minute polling is ~105k readings — too
    much to ship as JSON and too dense to chart). Input must be sorted
    oldest-first (the contract of :func:`get_readings`).

    Edge cases:
    - Empty input or non-positive ``bucket_seconds`` → returns input as-is.
    - Single-reading bucket → that reading's value is preserved (AVG of 1).
    """
    if not readings or bucket_seconds <= 0:
        return list(readings)

    out: list[dict] = []
    cur_bucket_start: int | None = None
    cur_values: list[float] = []
    cur_pid: str | None = None
    cur_pname: str | None = None

    def _flush():
        if cur_values and cur_bucket_start is not None:
            avg = round(sum(cur_values) / len(cur_values))
            out.append(
                {
                    "timestamp": datetime.fromtimestamp(
                        cur_bucket_start, tz=timezone.utc
                    ).isoformat(),
                    "patient_id": cur_pid,
                    "patient_name": cur_pname,
                    "glucose_value": avg,
                }
            )

    for r in readings:
        ts = datetime.fromisoformat(r["timestamp"])
        bucket_start = (int(ts.timestamp()) // bucket_seconds) * bucket_seconds
        if cur_bucket_start is None:
            cur_bucket_start = bucket_start
            cur_pid = r["patient_id"]
            cur_pname = r["patient_name"]
        if bucket_start != cur_bucket_start:
            _flush()
            cur_bucket_start = bucket_start
            cur_values = []
            cur_pid = r["patient_id"]
            cur_pname = r["patient_name"]
        cur_values.append(r["glucose_value"])

    _flush()
    return out


def iter_readings(
    db_path: str,
    patient_id: str,
    hours: int = 3,
    days: int | None = None,
):
    """Yield readings one row at a time without loading the full result set
    into memory.

    Same window semantics as :func:`get_readings`. Used by the CSV export
    endpoint behind ``StreamingResponse`` so that a year-long export of
    multiple patients does not spike memory. Yields dict rows in the same
    shape as ``get_readings`` (oldest-first).

    Empty generator when the DB file does not exist or the query fails
    (failure is logged at WARNING level, no exception propagates — same
    contract as :func:`get_readings`).
    """
    if days is not None:
        if not isinstance(days, int) or days <= 0:
            raise ValueError(f"days must be a positive int, got {days!r}")
        hours = days * 24
    elif hours <= 0:
        raise ValueError(f"hours must be a positive int, got {hours!r}")

    if not Path(db_path).exists():
        return

    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    engine = _get_engine(db_path)

    try:
        with engine.connect() as conn:
            # execution_options(stream_results=True) tells SQLAlchemy / DBAPI
            # to use a server-side cursor where supported (SQLite buffers in
            # the C layer so memory still stays modest, but the API is right
            # if the backend ever changes to Postgres etc.).
            result = conn.execution_options(stream_results=True, yield_per=1000).execute(
                text(
                    "SELECT timestamp, patient_id, patient_name, glucose_value "
                    "FROM readings "
                    "WHERE patient_id = :pid AND timestamp >= :since "
                    "ORDER BY timestamp ASC"
                ),
                {"pid": patient_id, "since": since},
            )
            for row in result:
                yield {
                    "timestamp": row[0],
                    "patient_id": row[1],
                    "patient_name": row[2],
                    "glucose_value": row[3],
                }
    except Exception as exc:
        logger.warning("Failed to stream reading history for patient %s: %s", patient_id, exc)
        return


def cleanup_old_readings(db_path: str, max_days: int = 3) -> int:
    """Delete readings older than *max_days* days.

    Returns the number of rows deleted.
    """
    if not Path(db_path).exists():
        return 0

    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_days)).isoformat()
    engine = _get_engine(db_path)

    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("DELETE FROM readings WHERE timestamp < :cutoff"),
                {"cutoff": cutoff},
            )
            conn.commit()
            deleted = result.rowcount
    except Exception as exc:
        logger.warning("Failed to clean up reading history: %s", exc)
        return 0

    if deleted:
        logger.debug("Cleaned up %d old reading(s) from history", deleted)
    return deleted
