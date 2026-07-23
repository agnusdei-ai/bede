"""
core/credential_hash.py — the one-way PBKDF2-HMAC-SHA256 hashing used for
verify-only secrets (the parent password override, the recovery code).
"""
from core.credential_hash import hash_secret, verify_secret


def test_verify_secret_accepts_the_correct_value():
    digest, salt = hash_secret("a-strong-password")
    assert verify_secret("a-strong-password", digest, salt) is True


def test_verify_secret_rejects_the_wrong_value():
    digest, salt = hash_secret("a-strong-password")
    assert verify_secret("a-different-password", digest, salt) is False


def test_hash_is_salted_differently_each_time():
    digest1, salt1 = hash_secret("same-secret")
    digest2, salt2 = hash_secret("same-secret")
    assert salt1 != salt2
    assert digest1 != digest2
    # Both still verify correctly against their own salt.
    assert verify_secret("same-secret", digest1, salt1) is True
    assert verify_secret("same-secret", digest2, salt2) is True


def test_verify_secret_rejects_a_hash_produced_with_a_different_salt():
    digest, _ = hash_secret("a-strong-password")
    _, other_salt = hash_secret("unrelated")
    assert verify_secret("a-strong-password", digest, other_salt) is False
