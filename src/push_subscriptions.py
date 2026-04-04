"""Browser Web-Push subscription persistence.

Each browser that the user authorises stores a *push subscription* — a JSON
object containing an endpoint URL and encryption keys.  This module manages
those subscriptions in a local SQLite database (``push_subscriptions.db``)
so that the alert engine can deliver notifications to all subscribed devices.

Database schema
---------------
``push_subscriptions`` (push_subscriptions.db)
  - id          INTEGER  PRIMARY KEY AUTOINCREMENT
  - endpoint    TEXT     NOT NULL UNIQUE   — the push service URL
  - p256dh      TEXT     NOT NULL          — browser's public ECDH key (base64url)
  - auth        TEXT     NOT NULL          — shared auth secret (base64url)
  - created_at  REAL     NOT NULL          — Unix timestamp

Usage
-----
Call :func:`init_db` once at startup with the database file path, then use
:func:`save_subscription`, :func:`delete_subscription`, and
:func:`get_all_subscriptions` for DML.
"""
import logging
import time
from typing import Optional

from src.db import connect_db

logger = logging.getLogger(__name__)

# Module-level path; set by init_db.
_db_path: Optional[str] = None

_DDL = """
CREATE TABLE IF NOT EXISTS push_subscriptions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint    TEXT    NOT NULL UNIQUE,
    p256dh      TEXT    NOT NULL,
    auth        TEXT    NOT NULL,
    created_at  REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_push_endpoint ON push_subscriptions (endpoint);
"""


def init_db(path: str) -> None:
    """Create the ``push_subscriptions`` table if it doesn't already exist.

    :param path: Absolute or relative filesystem path to the SQLite database.
    """
    global _db_path
    _db_path = path
    conn = connect_db(path)
    try:
        conn.executescript(_DDL)
        conn.commit()
    finally:
        conn.close()
    logger.debug("push_subscriptions DB initialised at %s", path)


def _get_path() -> str:
    if not _db_path:
        raise RuntimeError("push_subscriptions.init_db() has not been called")
    return _db_path


def save_subscription(endpoint: str, p256dh: str, auth: str) -> None:
    """Persist a push subscription, replacing any existing row for *endpoint*.

    :param endpoint: Push service endpoint URL.
    :param p256dh:   Browser public ECDH key (base64url, no padding).
    :param auth:     Authentication secret (base64url, no padding).
    """
    conn = connect_db(_get_path())
    try:
        conn.execute(
            """
            INSERT INTO push_subscriptions (endpoint, p256dh, auth, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(endpoint) DO UPDATE SET
                p256dh     = excluded.p256dh,
                auth       = excluded.auth,
                created_at = excluded.created_at
            """,
            (endpoint, p256dh, auth, time.time()),
        )
        conn.commit()
    finally:
        conn.close()
    logger.info("Push subscription saved for endpoint %s…", endpoint[:40])


def delete_subscription(endpoint: str) -> int:
    """Remove a push subscription by endpoint URL.

    :returns: Number of rows deleted (0 if the endpoint was not found).
    """
    conn = connect_db(_get_path())
    try:
        cur = conn.execute(
            "DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,)
        )
        conn.commit()
        deleted = cur.rowcount
    finally:
        conn.close()
    if deleted:
        logger.info("Push subscription removed for endpoint %s…", endpoint[:40])
    return deleted


def get_all_subscriptions() -> list[dict]:
    """Return all stored push subscriptions.

    Returns an empty list when the database has not been initialised yet
    (i.e. :func:`init_db` has not been called).

    :returns: List of dicts with keys ``endpoint``, ``p256dh``, ``auth``.
    """
    if not _db_path:
        return []
    conn = connect_db(_get_path())
    try:
        cur = conn.execute("SELECT endpoint, p256dh, auth FROM push_subscriptions")
        rows = cur.fetchall()
    finally:
        conn.close()
    return [{"endpoint": r[0], "p256dh": r[1], "auth": r[2]} for r in rows]
