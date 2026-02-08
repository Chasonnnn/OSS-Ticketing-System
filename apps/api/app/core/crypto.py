from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings


class EncryptionKeyError(RuntimeError):
    pass


def _load_key() -> bytes:
    settings = get_settings()
    raw = settings.ENCRYPTION_KEY_BASE64
    try:
        key = base64.b64decode(raw, validate=True)
    except Exception as e:  # noqa: BLE001
        raise EncryptionKeyError("ENCRYPTION_KEY_BASE64 must be valid base64") from e

    if len(key) != 32:
        raise EncryptionKeyError("ENCRYPTION_KEY_BASE64 must decode to 32 bytes (AES-256)")

    return key


def encrypt_bytes(*, plaintext: bytes, aad: bytes) -> bytes:
    key = _load_key()
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext, aad)
    return nonce + ciphertext


def decrypt_bytes(*, blob: bytes, aad: bytes) -> bytes:
    if len(blob) < 13:
        raise ValueError("Encrypted blob is too short")

    key = _load_key()
    nonce = blob[:12]
    ciphertext = blob[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, aad)
