import base64

import pytest

from cubicle.crypto import DecryptionError, decrypt, encrypt, mask


def test_round_trip():
    assert decrypt(encrypt("sk_live_secret")) == "sk_live_secret"


def test_round_trip_with_associated_data():
    blob = encrypt("value", aad="env:STRIPE_KEY")
    assert decrypt(blob, aad="env:STRIPE_KEY") == "value"


def test_associated_data_is_bound_to_the_record():
    """A ciphertext moved to another key must not decrypt."""
    blob = encrypt("value", aad="env:STRIPE_KEY")
    with pytest.raises(DecryptionError):
        decrypt(blob, aad="env:OTHER_KEY")


def test_every_record_gets_a_distinct_data_key():
    assert encrypt("same") != encrypt("same")


def test_tampering_is_detected():
    raw = bytearray(base64.b64decode(encrypt("value")))
    raw[-1] ^= 0xFF
    with pytest.raises(DecryptionError):
        decrypt(base64.b64encode(bytes(raw)).decode())


def test_garbage_raises_a_clear_error():
    with pytest.raises(DecryptionError):
        decrypt("not-base64-at-all!!")


def test_empty_values_round_trip():
    assert decrypt(encrypt("")) == ""


def test_mask_keeps_only_the_tail():
    assert mask("sk_live_4f81c9ba22d7").endswith("22d7")
    assert "4f81c9" not in mask("sk_live_4f81c9ba22d7")
    assert mask("ab") == "•" * 12
