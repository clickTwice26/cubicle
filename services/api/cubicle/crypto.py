"""Envelope encryption for stored configuration.

Every secret gets its own random 256-bit data key. The data key encrypts the
value with AES-256-GCM, and is itself wrapped with a key derived from the
cluster root key via HKDF. The root key never leaves this process, and the
database only ever holds wrapped material — a database dump on its own is not
enough to read a single secret.

Losing ``CUBICLE_MASTER_KEY`` means losing every stored secret. That is the
intended property: nothing off-node can decrypt them.
"""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .config import settings

_VERSION = b"\x01"
_INFO = b"cubicle-envelope-v1"


class DecryptionError(RuntimeError):
    """Raised when a stored value cannot be unwrapped with the current root key."""


def _root_key() -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"cubicle-root-salt",
        info=_INFO,
    ).derive(settings.master_key.encode())


_ROOT = _root_key()


def encrypt(plaintext: str, *, aad: str = "") -> str:
    """Wrap ``plaintext`` and return a base64 blob safe to store in Postgres."""
    dek = AESGCM.generate_key(bit_length=256)
    value_nonce = os.urandom(12)
    ciphertext = AESGCM(dek).encrypt(value_nonce, plaintext.encode(), aad.encode() or None)

    wrap_nonce = os.urandom(12)
    wrapped = AESGCM(_ROOT).encrypt(wrap_nonce, dek, _INFO)

    blob = b"".join(
        [
            _VERSION,
            wrap_nonce,
            len(wrapped).to_bytes(2, "big"),
            wrapped,
            value_nonce,
            ciphertext,
        ]
    )
    return base64.b64encode(blob).decode()


def decrypt(blob: str, *, aad: str = "") -> str:
    try:
        raw = base64.b64decode(blob)
        if raw[:1] != _VERSION:
            raise DecryptionError("unsupported envelope version")
        pos = 1
        wrap_nonce, pos = raw[pos : pos + 12], pos + 12
        wrapped_len = int.from_bytes(raw[pos : pos + 2], "big")
        pos += 2
        wrapped, pos = raw[pos : pos + wrapped_len], pos + wrapped_len
        value_nonce, pos = raw[pos : pos + 12], pos + 12
        ciphertext = raw[pos:]

        dek = AESGCM(_ROOT).decrypt(wrap_nonce, wrapped, _INFO)
        return AESGCM(dek).decrypt(value_nonce, ciphertext, aad.encode() or None).decode()
    except DecryptionError:
        raise
    except Exception as exc:  # noqa: BLE001 - any failure here is the same failure
        raise DecryptionError(
            "value could not be decrypted — CUBICLE_MASTER_KEY has changed or the record is corrupt"
        ) from exc


def mask(value: str, *, keep: int = 4) -> str:
    """Console-safe rendering of a secret: last few characters only."""
    if len(value) <= keep:
        return "•" * 12
    return "•" * 14 + value[-keep:]
