"""Authentication module: session management and credential verification.

Dashboard authentication is handled via the ``dashboard_auth`` section of
``config.yaml``, which is **separate** from the LibreLinkUp API credentials
stored under the ``librelinkup`` section.  Passwords are stored as
PBKDF2-HMAC-SHA256 hashes — never in plain text.
"""
import hashlib
import hmac
import logging
import os
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = PROJECT_ROOT / "config.yaml"

SESSION_TTL = 24 * 3600  # 24 hours

_SESSIONS_DB = str(PROJECT_ROOT / "sessions.db")

_CREATE_SESSIONS_TABLE = """
CREATE TABLE IF NOT EXISTS sessions (
    token       TEXT PRIMARY KEY,
    expires_at  REAL NOT NULL
);
"""
_CREATE_SESSIONS_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);"
)


class SessionManager:
    """Manages persistent session tokens backed by SQLite with TTL."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path if db_path is not None else _SESSIONS_DB
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._get_conn() as conn:
                conn.execute(_CREATE_SESSIONS_TABLE)
                conn.execute(_CREATE_SESSIONS_INDEX)
                conn.commit()
        except sqlite3.OperationalError as exc:
            logger.error("Failed to initialise sessions DB at %s: %s", self._db_path, exc)

    def _get_conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path, timeout=10)

    def create_session(self) -> str:
        """Create a new session token valid for SESSION_TTL seconds."""
        token = secrets.token_hex(32)
        expires_at = time.time() + SESSION_TTL
        try:
            with self._get_conn() as conn:
                conn.execute(
                    "INSERT INTO sessions (token, expires_at) VALUES (?, ?)",
                    (token, expires_at),
                )
                conn.commit()
        except sqlite3.OperationalError as exc:
            logger.error("Failed to create session: %s", exc)
        return token

    def is_valid(self, token: Optional[str]) -> bool:
        """Return True if the token exists and has not expired."""
        if not token:
            return False
        try:
            with self._get_conn() as conn:
                row = conn.execute(
                    "SELECT expires_at FROM sessions WHERE token = ?", (token,)
                ).fetchone()
                if row is None:
                    return False
                expires_at = row[0]
                if time.time() > expires_at:
                    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
                    conn.commit()
                    return False
                return True
        except sqlite3.OperationalError as exc:
            logger.error("Failed to validate session: %s", exc)
            return False

    def invalidate(self, token: str) -> None:
        """Remove a session token from the store."""
        try:
            with self._get_conn() as conn:
                conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
                conn.commit()
        except sqlite3.OperationalError as exc:
            logger.error("Failed to invalidate session: %s", exc)

    def clear_all(self) -> None:
        """Remove all sessions (used in tests)."""
        try:
            with self._get_conn() as conn:
                conn.execute("DELETE FROM sessions")
                conn.commit()
        except sqlite3.OperationalError as exc:
            logger.error("Failed to clear all sessions: %s", exc)

    def cleanup_expired(self) -> int:
        """Delete expired sessions and return the number of rows removed."""
        try:
            with self._get_conn() as conn:
                cursor = conn.execute(
                    "DELETE FROM sessions WHERE expires_at < ?", (time.time(),)
                )
                conn.commit()
                return cursor.rowcount
        except sqlite3.OperationalError as exc:
            logger.error("Failed to clean up expired sessions: %s", exc)
            return 0


session_manager = SessionManager(db_path=_SESSIONS_DB)

# ---------------------------------------------------------------------------
# Password hashing helpers
# ---------------------------------------------------------------------------

_HASH_PREFIX = "pbkdf2:sha256"
# 260 000 iterations aligns with the OWASP 2023 recommendation for
# PBKDF2-HMAC-SHA256 on commodity hardware.
_PBKDF2_ITERATIONS = 260_000


def hash_password(password: str) -> str:
    """Return a PBKDF2-HMAC-SHA256 hash of *password*.

    The returned string encodes the algorithm, iteration count, salt, and
    derived key in a single portable string:

        ``pbkdf2:sha256:<iterations>:<salt_hex>:<key_hex>``
    """
    salt = os.urandom(16)
    key = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS
    )
    return f"{_HASH_PREFIX}:{_PBKDF2_ITERATIONS}:{salt.hex()}:{key.hex()}"


def check_password(password: str, hashed: str) -> bool:
    """Return True if *password* matches the stored PBKDF2 *hashed* value.

    Uses ``hmac.compare_digest`` for the final key comparison to prevent
    timing-based attacks.
    """
    try:
        parts = hashed.split(":")
        if len(parts) != 5 or parts[0] != "pbkdf2" or parts[1] != "sha256":
            return False
        iterations = int(parts[2])
        if iterations <= 0 or iterations > 1_000_000_000:
            return False
        salt = bytes.fromhex(parts[3])
        stored_key = bytes.fromhex(parts[4])
        key = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, iterations
        )
        return hmac.compare_digest(stored_key, key)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


def is_configured() -> bool:
    """Return True if config.yaml exists on disk."""
    return _CONFIG_PATH.exists()


def verify_credentials(username: str, password: str) -> bool:
    """Verify dashboard credentials against ``dashboard_auth`` in config.yaml.

    The dashboard ``username`` and ``password_hash`` are stored under the
    ``dashboard_auth`` section and are **independent** of the LibreLinkUp
    credentials kept under ``librelinkup``.

    Uses ``hmac.compare_digest`` for the username comparison and PBKDF2 for
    the password check to prevent timing attacks.
    """
    if not _CONFIG_PATH.exists():
        return False
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            config = yaml.safe_load(f)
        dash_auth = config.get("dashboard_auth", {})
        stored_username = str(dash_auth.get("username", ""))
        stored_hash = str(dash_auth.get("password_hash", ""))
        if not hmac.compare_digest(stored_username, username):
            return False
        return check_password(password, stored_hash)
    except Exception:
        return False
