"""Centralised SQLite connection factory for family-glucose-monitor.

All modules that need a SQLite connection should use :func:`connect_db`
instead of calling ``sqlite3.connect`` directly.  This ensures consistent
pragmas (WAL mode, foreign-key enforcement, timeout) across the codebase.
"""
import sqlite3


def connect_db(path: str) -> sqlite3.Connection:
    """Return an open SQLite connection configured for this application.

    * ``PRAGMA journal_mode=WAL`` — allows concurrent reads alongside writes,
      which is beneficial when the dashboard and the polling daemon both access
      the same database.
    * ``PRAGMA foreign_keys=ON`` — enforce referential integrity.
    * ``timeout=10`` — wait up to 10 seconds before raising ``OperationalError``
      on a locked database rather than failing immediately.
    """
    conn = sqlite3.connect(path, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn
