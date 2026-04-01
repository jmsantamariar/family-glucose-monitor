"""Symmetric encryption helpers for sensitive configuration values.

Uses Fernet (AES-128-CBC + HMAC-SHA256) from the ``cryptography`` library.
The encryption key is derived from a master secret stored in ``.secret_key``
at the project root.  This file is created automatically on first use with
restricted permissions (0600).

.. warning::
   Losing ``.secret_key`` means any ``encrypted:`` values in ``config.yaml``
   become unreadable.  Re-run the setup wizard to reconfigure.
"""
import base64
import logging
import os
import stat
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SECRET_KEY_FILE = PROJECT_ROOT / ".secret_key"

_ENCRYPTED_PREFIX = "encrypted:"


def _get_or_create_key() -> bytes:
    """Return the Fernet key, creating .secret_key if it does not exist.

    The raw secret is 32 random bytes.  A deterministic Fernet-compatible
    key is derived via SHA-256 and base64url encoding so the file content
    is human-safe (no binary).
    """
    if _SECRET_KEY_FILE.exists():
        raw = bytes.fromhex(_SECRET_KEY_FILE.read_text().strip())
    else:
        raw = os.urandom(32)
        _SECRET_KEY_FILE.write_text(raw.hex())
        # Restrict permissions: owner read/write only
        try:
            os.chmod(_SECRET_KEY_FILE, stat.S_IRUSR | stat.S_IWUSR)  # 0600
        except OSError:
            logger.warning("Could not set permissions on %s", _SECRET_KEY_FILE)
        logger.info("Created new encryption key at %s", _SECRET_KEY_FILE)

    # Derive a Fernet-compatible 32-byte key via HKDF-SHA256
    derived = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"family-glucose-monitor-fernet-key",
    ).derive(raw)
    return base64.urlsafe_b64encode(derived)


def encrypt_value(plaintext: str) -> str:
    """Encrypt *plaintext* and return a string prefixed with 'encrypted:'.

    The returned string is safe to store in YAML.
    """
    key = _get_or_create_key()
    f = Fernet(key)
    token = f.encrypt(plaintext.encode("utf-8"))
    return f"{_ENCRYPTED_PREFIX}{token.decode('ascii')}"


def decrypt_value(stored: str) -> str:
    """Decrypt *stored* value.  If it is not encrypted (no prefix), return as-is.

    This provides backward compatibility: plain-text passwords in existing
    config files continue to work until re-encrypted.
    """
    if not stored.startswith(_ENCRYPTED_PREFIX):
        return stored  # plain-text fallback for backward compat
    key = _get_or_create_key()
    f = Fernet(key)
    token = stored[len(_ENCRYPTED_PREFIX):]
    try:
        return f.decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken:
        logger.error("Failed to decrypt value — key may have changed")
        raise


def is_encrypted(value: str) -> bool:
    """Return True if the value is encrypted (has the prefix)."""
    return value.startswith(_ENCRYPTED_PREFIX)
