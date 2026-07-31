import pytest

from cubicle import security


@pytest.mark.parametrize(
    "password",
    ["short", "alllowercaseletters", "Password1234", "123456789012345"],
)
def test_weak_passwords_are_rejected(password):
    assert not security.check_password_policy(password).ok


@pytest.mark.parametrize("password", ["Correct-Horse-42", "aB3$aB3$aB3$", "Tr0ub4dor&3xyz"])
def test_reasonable_passwords_are_accepted(password):
    assert security.check_password_policy(password).ok


def test_password_hashing_round_trip():
    digest = security.hash_password("Correct-Horse-42")
    assert digest.startswith("$argon2")
    assert security.verify_password(digest, "Correct-Horse-42")
    assert not security.verify_password(digest, "Correct-Horse-43")


def test_verify_tolerates_a_corrupt_hash():
    assert not security.verify_password("not-a-hash", "anything")


def test_api_keys_are_prefixed_and_only_stored_hashed():
    token, prefix, digest = security.generate_api_key()
    assert token.startswith("cbcl_")
    assert token.startswith(prefix)
    assert digest != token
    assert security.hash_api_key(token) == digest
    assert security.api_key_prefix(token) == prefix


def test_api_keys_are_unique():
    assert security.generate_api_key()[0] != security.generate_api_key()[0]
