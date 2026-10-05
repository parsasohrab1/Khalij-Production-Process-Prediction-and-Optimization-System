"""AES-256-GCM encryption utility for sensitive data at rest (NFR-SEC-02).

The key is read from the DATA_ENCRYPTION_KEY environment variable (32 bytes, Base64).
If the key is not set, encryption is disabled and data is stored as plaintext
(suitable for the development environment; in production it must be enabled).
"""
from __future__ import annotations

import base64
import logging
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

_PREFIX = "aes256gcm:"


def _load_key() -> bytes | None:
    raw = os.getenv("DATA_ENCRYPTION_KEY", "").strip()
    if not raw:
        return None
    try:
        key = base64.b64decode(raw)
        if len(key) != 32:
            logger.error("DATA_ENCRYPTION_KEY must be 32 bytes (AES-256); encryption disabled.")
            return None
        return key
    except Exception:  # noqa: BLE001
        logger.error("DATA_ENCRYPTION_KEY is invalid; encryption disabled.")
        return None


def encrypt_at_rest(plaintext: str) -> str:
    """Encrypt text with AES-256-GCM. Output: aes256gcm:<nonce_b64>:<ciphertext_b64>."""
    key = _load_key()
    if key is None or not plaintext:
        return plaintext
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return (
        f"{_PREFIX}{base64.b64encode(nonce).decode('ascii')}:"
        f"{base64.b64encode(ciphertext).decode('ascii')}"
    )


def decrypt_at_rest(value: str) -> str:
    """Decrypt an encrypted value; if it has no prefix, returns the same value."""
    if not value or not value.startswith(_PREFIX):
        return value
    key = _load_key()
    if key is None:
        raise RuntimeError("Data is encrypted but DATA_ENCRYPTION_KEY is not set.")
    try:
        _, nonce_b64, ct_b64 = value.split(":", 2)
        nonce = base64.b64decode(nonce_b64)
        ciphertext = base64.b64decode(ct_b64)
        aesgcm = AESGCM(key)
        return aesgcm.decrypt(nonce, ciphertext, None).decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("Decrypting the encrypted data failed.") from exc


def generate_key_b64() -> str:
    """Generate a random 32-byte key as Base64 (to put in .env)."""
    return base64.b64encode(os.urandom(32)).decode("ascii")
