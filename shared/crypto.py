"""ابزار رمزنگاری AES-256-GCM برای داده‌های حساس در حالت ذخیره‌سازی (NFR-SEC-02).

کلید از متغیر محیطی DATA_ENCRYPTION_KEY (۳۲ بایت، Base64) خوانده می‌شود.
اگر کلید تنظیم نشده باشد، رمزنگاری غیرفعال است و داده به‌صورت plaintext ذخیره می‌شود
(مناسب محیط توسعه؛ در production باید حتماً فعال باشد).
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
            logger.error("DATA_ENCRYPTION_KEY باید ۳۲ بایت (AES-256) باشد؛ رمزنگاری غیرفعال شد.")
            return None
        return key
    except Exception:  # noqa: BLE001
        logger.error("DATA_ENCRYPTION_KEY نامعتبر است؛ رمزنگاری غیرفعال شد.")
        return None


def encrypt_at_rest(plaintext: str) -> str:
    """رمزنگاری متن با AES-256-GCM. خروجی: aes256gcm:<nonce_b64>:<ciphertext_b64>."""
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
    """بازگشایی مقدار رمزشده؛ اگر prefix نداشته باشد همان مقدار را برمی‌گرداند."""
    if not value or not value.startswith(_PREFIX):
        return value
    key = _load_key()
    if key is None:
        raise RuntimeError("داده رمزشده است ولی DATA_ENCRYPTION_KEY تنظیم نشده.")
    try:
        _, nonce_b64, ct_b64 = value.split(":", 2)
        nonce = base64.b64decode(nonce_b64)
        ciphertext = base64.b64decode(ct_b64)
        aesgcm = AESGCM(key)
        return aesgcm.decrypt(nonce, ciphertext, None).decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("بازگشایی داده رمزشده ناموفق بود.") from exc


def generate_key_b64() -> str:
    """تولید یک کلید تصادفی ۳۲ بایتی به صورت Base64 (برای قرار دادن در .env)."""
    return base64.b64encode(os.urandom(32)).decode("ascii")
