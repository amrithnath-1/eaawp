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

from cryptography.fernet import Fernet, MultiFernet


def _fernet_for(secret: str) -> Fernet:
    # Derive a 32-byte key from the secret using SHA-256
    raw = hashlib.sha256(secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(raw))


def _get_fernet() -> MultiFernet:
    """Encrypt with ENCRYPTION_KEY when set; always able to decrypt data written
    under the SECRET_KEY-derived key (so enabling ENCRYPTION_KEY loses nothing)."""
    from app.config import settings
    keys = []
    if settings.encryption_key:
        keys.append(_fernet_for(settings.encryption_key))
    keys.append(_fernet_for(settings.secret_key))
    return MultiFernet(keys)


def encrypt_password(plain: str) -> str:
    """Encrypt a plain-text password and return the ciphertext as a string."""
    return _get_fernet().encrypt(plain.encode()).decode()


def decrypt_password(cipher: str) -> str:
    """Decrypt a previously-encrypted password. Raises on tampered data."""
    return _get_fernet().decrypt(cipher.encode()).decode()
