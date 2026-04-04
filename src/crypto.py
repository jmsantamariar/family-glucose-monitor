"""Symmetric encryption helpers for sensitive configuration values.

Uses Fernet (AES-128-CBC + HMAC-SHA256) from the ``cryptography`` library.
The master secret used to derive the Fernet key can be supplied in three ways,
in order of precedence:

1. **Environment variable** ``FGM_MASTER_KEY`` — a 64-character hex string
   representing 32 raw bytes.  Recommended for production deployments (Docker
   secrets, Kubernetes secrets, etc.).
2. **``.secret_key`` file** at the project root — created automatically on
   first use with restricted permissions (0600).  Convenient for local/dev use.

.. warning::
   Losing the master secret means any ``encrypted:`` values in ``config.yaml``
   become unreadable.  Re-run the setup wizard to reconfigure.

   If ``FGM_MASTER_KEY`` is used in production, store it in a secrets manager
   or inject it as a Docker secret — do **not** hard-code it in source.
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
    """Return the Fernet key, using the configured master secret source.

    Precedence:
    1. ``FGM_MASTER_KEY`` environment variable (32 bytes as 64 hex chars).
    2. ``.secret_key`` file at project root (created if absent).
    """
    env_secret = os.environ.get("FGM_MASTER_KEY", "").strip()
    if env_secret:
        try:
            raw = bytes.fromhex(env_secret)
        except ValueError:
            raise ValueError(
                "FGM_MASTER_KEY must be a 64-character hex string (32 bytes). "
                "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        if len(raw) != 32:
            raise ValueError(
                f"FGM_MASTER_KEY decoded to {len(raw)} bytes; exactly 32 are required."
            )
    elif _SECRET_KEY_FILE.exists():
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
    except InvalidToken as exc:
        logger.error(
            "Failed to decrypt the LibreLinkUp password — the encryption key may have changed "
            "or the value was corrupted.  "
            "Edit config.yaml and set the password as plain text so it can be re-encrypted."
        )
        raise ValueError(
            "Error: no se pudo desencriptar la contraseña de LibreLinkUp. "
            "Edita config.yaml y pon la contraseña en texto plano para que sea reencriptada."
        ) from exc


def is_encrypted(value: str) -> bool:
    """Return True if the value is encrypted (has the prefix)."""
    return value.startswith(_ENCRYPTED_PREFIX)
