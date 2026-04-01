"""Tests for src.crypto module."""
import stat
from unittest.mock import patch

import pytest
from cryptography.fernet import InvalidToken

import src.crypto as crypto_module
from src.crypto import decrypt_value, encrypt_value, is_encrypted


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _patch_key_file(tmp_path):
    """Return a context manager that redirects _SECRET_KEY_FILE to tmp_path."""
    return patch.object(crypto_module, "_SECRET_KEY_FILE", tmp_path / ".secret_key")


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


def test_encrypt_decrypt_roundtrip(tmp_path):
    """Encrypting then decrypting must yield the original plaintext."""
    with _patch_key_file(tmp_path):
        encrypted = encrypt_value("supersecret")
        result = decrypt_value(encrypted)
    assert result == "supersecret"


def test_encrypted_value_has_prefix(tmp_path):
    """Encrypted value must start with the 'encrypted:' prefix."""
    with _patch_key_file(tmp_path):
        encrypted = encrypt_value("mypassword")
    assert encrypted.startswith("encrypted:")


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------


def test_decrypt_plaintext_returns_as_is(tmp_path):
    """decrypt_value must return plain-text values unchanged (no prefix)."""
    with _patch_key_file(tmp_path):
        result = decrypt_value("plaintext_password")
    assert result == "plaintext_password"


# ---------------------------------------------------------------------------
# is_encrypted helper
# ---------------------------------------------------------------------------


def test_is_encrypted_true(tmp_path):
    with _patch_key_file(tmp_path):
        encrypted = encrypt_value("value")
    assert is_encrypted(encrypted) is True


def test_is_encrypted_false():
    assert is_encrypted("plaintext") is False


# ---------------------------------------------------------------------------
# Key file creation and permissions
# ---------------------------------------------------------------------------


def test_key_file_created_on_first_use(tmp_path):
    """_SECRET_KEY_FILE must be created automatically if it does not exist."""
    key_file = tmp_path / ".secret_key"
    assert not key_file.exists()
    with _patch_key_file(tmp_path):
        encrypt_value("test")
    assert key_file.exists()


def test_key_file_created_with_restricted_permissions(tmp_path):
    """The created .secret_key must have mode 0600 (owner r/w only)."""
    key_file = tmp_path / ".secret_key"
    with _patch_key_file(tmp_path):
        encrypt_value("test")
    mode = key_file.stat().st_mode
    # Only owner read+write bits should be set (no group/other)
    assert mode & stat.S_IRUSR
    assert mode & stat.S_IWUSR
    assert not (mode & stat.S_IRGRP)
    assert not (mode & stat.S_IROTH)


# ---------------------------------------------------------------------------
# Wrong key raises InvalidToken
# ---------------------------------------------------------------------------


def test_decrypt_with_wrong_key_raises(tmp_path):
    """Decrypting with a different key must raise cryptography.fernet.InvalidToken."""
    key_file_a = tmp_path / ".secret_key_a"
    key_file_b = tmp_path / ".secret_key_b"

    # Encrypt with key A
    with patch.object(crypto_module, "_SECRET_KEY_FILE", key_file_a):
        encrypted = encrypt_value("my_password")

    # Attempt to decrypt with key B (a fresh, different key)
    with patch.object(crypto_module, "_SECRET_KEY_FILE", key_file_b):
        with pytest.raises(InvalidToken):
            decrypt_value(encrypted)


def test_hkdf_round_trip(tmp_path):
    """Encrypting and decrypting with the same HKDF-derived key must yield the original value."""
    with _patch_key_file(tmp_path):
        plaintext = "sensitive-config-value"
        encrypted = encrypt_value(plaintext)
        assert is_encrypted(encrypted)
        result = decrypt_value(encrypted)
    assert result == plaintext
