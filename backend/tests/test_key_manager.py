import json

import pytest

from app.security.key_manager import (
    DATA_KEY_BYTES,
    KeyEnvelopeError,
    create_key_envelope,
    unlock_with_passphrase,
    unlock_with_recovery_key,
)


def test_data_key_can_be_unlocked_by_passphrase_or_recovery_key():
    envelope, recovery_key = create_key_envelope("test passphrase")
    serialized_envelope = json.loads(json.dumps(envelope))

    passphrase_data_key = unlock_with_passphrase(serialized_envelope, "test passphrase")
    recovery_data_key = unlock_with_recovery_key(serialized_envelope, recovery_key)

    assert len(passphrase_data_key) == DATA_KEY_BYTES
    assert passphrase_data_key == recovery_data_key
    assert "test passphrase" not in json.dumps(envelope)
    assert recovery_key not in json.dumps(envelope)


def test_wrong_passphrase_cannot_unlock_data_key():
    envelope, _ = create_key_envelope("test passphrase")

    with pytest.raises(KeyEnvelopeError, match="Unable to unlock"):
        unlock_with_passphrase(envelope, "incorrect passphrase")


def test_wrong_recovery_key_cannot_unlock_data_key():
    envelope, _ = create_key_envelope("test passphrase")

    with pytest.raises(KeyEnvelopeError, match="Unable to unlock"):
        unlock_with_recovery_key(envelope, "A" * 43)
