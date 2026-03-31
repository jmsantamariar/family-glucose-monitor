"""Authentication module: session management and credential verification."""
import hmac
import secrets
import time
from pathlib import Path
from typing import Optional

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = PROJECT_ROOT / "config.yaml"

# In-memory session store: token -> expiry timestamp
_sessions: dict[str, float] = {}

SESSION_TTL = 24 * 3600  # 24 hours


class SessionManager:
    """Manages in-memory session tokens with TTL."""

    def create_session(self) -> str:
        """Create a new session token valid for SESSION_TTL seconds."""
        token = secrets.token_hex(32)
        _sessions[token] = time.time() + SESSION_TTL
        return token

    def is_valid(self, token: Optional[str]) -> bool:
        """Return True if the token exists and has not expired."""
        if not token:
            return False
        expiry = _sessions.get(token)
        if expiry is None:
            return False
        if time.time() > expiry:
            del _sessions[token]
            return False
        return True

    def invalidate(self, token: str) -> None:
        """Remove a session token from the store."""
        _sessions.pop(token, None)

    def clear_all(self) -> None:
        """Remove all sessions (used in tests)."""
        _sessions.clear()


session_manager = SessionManager()


def is_configured() -> bool:
    """Return True if config.yaml exists on disk."""
    return _CONFIG_PATH.exists()


def verify_credentials(email: str, password: str) -> bool:
    """Verify email and password against the credentials in config.yaml.

    Uses ``hmac.compare_digest`` for constant-time comparison to prevent
    timing-based attacks.
    """
    if not _CONFIG_PATH.exists():
        return False
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            config = yaml.safe_load(f)
        ll = config.get("librelinkup", {})
        stored_email = str(ll.get("email", ""))
        stored_password = str(ll.get("password", ""))
        email_ok = hmac.compare_digest(stored_email, email)
        password_ok = hmac.compare_digest(stored_password, password)
        return email_ok and password_ok
    except Exception:
        return False
