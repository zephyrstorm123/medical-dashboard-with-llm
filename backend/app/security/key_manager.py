"""Create and unlock the wrapped database data key."""

from __future__ import annotations

import base64
import binascii
import os
from typing import Any

from argon2.low_level import Type, hash_secret_raw
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

DATA_KEY_BYTES = 32
SALT_BYTES = 16
NONCE_BYTES = 12
ARGON2_TIME_COST = 3
ARGON2_MEMORY_COST_KIB = 64 * 1024
ARGON2_PARALLELISM = 1
ENVELOPE_VERSION = 1

_AAD = {
    "passphrase": b"clinic-dashboard:data-key:passphrase:v1",
    "recovery": b"clinic-dashboard:data-key:recovery:v1",
}


class KeyEnvelopeError(ValueError):
    """Raised when a key envelope is invalid or cannot be unlocked."""


def _encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _decode(value: Any, field: str) -> bytes:
    if not isinstance(value, str):
        raise KeyEnvelopeError(f"Invalid key envelope field: {field}")
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as error:
        raise KeyEnvelopeError(f"Invalid key envelope field: {field}") from error


def _derive_wrapping_key(passphrase: str, salt: bytes) -> bytes:
    if not passphrase:
        raise ValueError("Passphrase must not be empty")
    return hash_secret_raw(
        secret=passphrase.encode("utf-8"),
        salt=salt,
        time_cost=ARGON2_TIME_COST,
        memory_cost=ARGON2_MEMORY_COST_KIB,
        parallelism=ARGON2_PARALLELISM,
        hash_len=DATA_KEY_BYTES,
        type=Type.ID,
    )


def _wrap_data_key(data_key: bytes, wrapping_key: bytes, purpose: str) -> dict[str, str]:
    nonce = os.urandom(NONCE_BYTES)
    ciphertext = AESGCM(wrapping_key).encrypt(nonce, data_key, _AAD[purpose])
    return {"nonce": _encode(nonce), "ciphertext": _encode(ciphertext)}


def _unwrap_data_key(wrapped_key: Any, wrapping_key: bytes, purpose: str) -> bytes:
    if not isinstance(wrapped_key, dict):
        raise KeyEnvelopeError("Invalid key envelope: missing wrapped data key")
    nonce = _decode(wrapped_key.get("nonce"), "nonce")
    ciphertext = _decode(wrapped_key.get("ciphertext"), "ciphertext")
    if len(nonce) != NONCE_BYTES:
        raise KeyEnvelopeError("Invalid key envelope nonce length")
    try:
        data_key = AESGCM(wrapping_key).decrypt(nonce, ciphertext, _AAD[purpose])
    except InvalidTag as error:
        raise KeyEnvelopeError("Unable to unlock data key with provided credential") from error
    if len(data_key) != DATA_KEY_BYTES:
        raise KeyEnvelopeError("Invalid data key length")
    return data_key


def create_key_envelope(passphrase: str) -> tuple[dict[str, Any], str]:
    """Create a random data key wrapped by a passphrase and a recovery key."""
    if not passphrase:
        raise ValueError("Passphrase must not be empty")

    data_key = os.urandom(DATA_KEY_BYTES)
    salt = os.urandom(SALT_BYTES)
    recovery_key_bytes = os.urandom(DATA_KEY_BYTES)
    recovery_key = base64.urlsafe_b64encode(recovery_key_bytes).decode("ascii").rstrip("=")
    passphrase_key = _derive_wrapping_key(passphrase, salt)

    envelope = {
        "format_version": ENVELOPE_VERSION,
        "cipher": "AES-256-GCM",
        "kdf": {
            "algorithm": "Argon2id",
            "salt": _encode(salt),
            "time_cost": ARGON2_TIME_COST,
            "memory_cost_kib": ARGON2_MEMORY_COST_KIB,
            "parallelism": ARGON2_PARALLELISM,
        },
        "wrapped_data_key": {
            "passphrase": _wrap_data_key(data_key, passphrase_key, "passphrase"),
            "recovery": _wrap_data_key(data_key, recovery_key_bytes, "recovery"),
        },
    }
    return envelope, recovery_key


def _validate_envelope(envelope: Any) -> tuple[bytes, dict[str, Any]]:
    if not isinstance(envelope, dict):
        raise KeyEnvelopeError("Invalid key envelope")
    if envelope.get("format_version") != ENVELOPE_VERSION:
        raise KeyEnvelopeError("Unsupported key envelope version")
    if envelope.get("cipher") != "AES-256-GCM":
        raise KeyEnvelopeError("Unsupported key envelope cipher")

    kdf = envelope.get("kdf")
    if not isinstance(kdf, dict) or kdf.get("algorithm") != "Argon2id":
        raise KeyEnvelopeError("Unsupported key derivation function")
    expected_parameters = {
        "time_cost": ARGON2_TIME_COST,
        "memory_cost_kib": ARGON2_MEMORY_COST_KIB,
        "parallelism": ARGON2_PARALLELISM,
    }
    if any(kdf.get(name) != value for name, value in expected_parameters.items()):
        raise KeyEnvelopeError("Unsupported Argon2id parameters")
    salt = _decode(kdf.get("salt"), "salt")
    if len(salt) != SALT_BYTES:
        raise KeyEnvelopeError("Invalid key envelope salt length")

    wrapped_keys = envelope.get("wrapped_data_key")
    if not isinstance(wrapped_keys, dict):
        raise KeyEnvelopeError("Invalid key envelope: missing wrapped data key")
    return salt, wrapped_keys


def unlock_with_passphrase(envelope: Any, passphrase: str) -> bytes:
    """Recover the data key using the passphrase stored for this envelope."""
    salt, wrapped_keys = _validate_envelope(envelope)
    wrapping_key = _derive_wrapping_key(passphrase, salt)
    return _unwrap_data_key(wrapped_keys.get("passphrase"), wrapping_key, "passphrase")


def unlock_with_recovery_key(envelope: Any, recovery_key: str) -> bytes:
    """Recover the data key using the separately stored recovery key."""
    _, wrapped_keys = _validate_envelope(envelope)
    try:
        recovery_key_bytes = base64.urlsafe_b64decode(recovery_key + "=" * (-len(recovery_key) % 4))
    except (binascii.Error, ValueError) as error:
        raise KeyEnvelopeError("Invalid recovery key") from error
    if len(recovery_key_bytes) != DATA_KEY_BYTES:
        raise KeyEnvelopeError("Invalid recovery key length")
    return _unwrap_data_key(wrapped_keys.get("recovery"), recovery_key_bytes, "recovery")
