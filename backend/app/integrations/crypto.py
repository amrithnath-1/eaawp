"""
EAAWP Credential Encryption

Passwords for data connections are encrypted at rest using Fernet
(AES-128-CBC with HMAC-SHA256) derived from the SECRET_KEY setting.

The derived key is consistent across restarts so stored passwords can
be decrypted. The raw password is NEVER returned in API responses.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet


def _get_fernet() -> Fernet:
    from app.config import settings
    # Derive a 32-byte key from SECRET_KEY using SHA-256
    raw = hashlib.sha256(settings.secret_key.encode()).digest()
    key = base64.urlsafe_b64encode(raw)
    return Fernet(key)


def encrypt_password(plain: str) -> str:
    """Encrypt a plain-text password and return the ciphertext as a string."""
    return _get_fernet().encrypt(plain.encode()).decode()


def decrypt_password(cipher: str) -> str:
    """Decrypt a previously-encrypted password. Raises on tampered data."""
    return _get_fernet().decrypt(cipher.encode()).decode()
