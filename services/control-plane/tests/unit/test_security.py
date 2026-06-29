"""Cryptographic primitives: API-key generation, hashing, JWT round-trips.

If any of these regress, the platform's authentication is compromised, so they
are tested directly and adversarially."""

import datetime as dt
import uuid

import jwt
import pytest

from touchstone_control.core.config import Settings
from touchstone_control.core.security import SecurityService


@pytest.fixture
def security() -> SecurityService:
    # Lower Argon2 cost for fast tests; production uses settings defaults.
    return SecurityService(Settings(argon2_time_cost=1, argon2_memory_cost=8192))


def test_api_key_format_and_roundtrip(security):
    gen = security.generate_api_key()
    assert gen.plaintext.startswith("tsk_")
    assert gen.plaintext.count("_") == 2
    parsed = security.parse_api_key(gen.plaintext)
    assert parsed is not None
    key_id, secret = parsed
    assert key_id == gen.key_id
    assert security.verify_api_key_secret(secret, gen.secret_hash)


def test_plaintext_secret_is_not_in_hash(security):
    gen = security.generate_api_key()
    _, secret = security.parse_api_key(gen.plaintext)
    # The stored hash must not contain the raw secret.
    assert secret not in gen.secret_hash


def test_wrong_secret_is_rejected(security):
    gen = security.generate_api_key()
    assert not security.verify_api_key_secret("not-the-secret", gen.secret_hash)


def test_malformed_keys_return_none(security):
    assert security.parse_api_key("garbage") is None
    assert security.parse_api_key("wrong_prefix_x") is None
    assert security.parse_api_key("tsk__") is None


def test_two_keys_are_unique(security):
    a = security.generate_api_key()
    b = security.generate_api_key()
    assert a.key_id != b.key_id
    assert a.plaintext != b.plaintext


def test_jwt_roundtrip(security):
    uid, oid = uuid.uuid4(), uuid.uuid4()
    token = security.issue_access_token(user_id=uid, org_id=oid)
    claims = security.decode_token(token)
    assert claims["sub"] == str(uid)
    assert claims["org"] == str(oid)
    assert claims["type"] == "access"


def test_expired_jwt_is_rejected(security):
    token = security.issue_access_token(user_id=uuid.uuid4(), org_id=uuid.uuid4())
    # Tamper the exp far into the past by decoding without verify then re-signing.
    payload = security.decode_token(token)
    payload["exp"] = dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)
    forged = jwt.encode(payload, security._settings.jwt_secret.get_secret_value(),
                        algorithm="HS256")
    with pytest.raises(jwt.ExpiredSignatureError):
        security.decode_token(forged)


def test_tampered_signature_is_rejected(security):
    token = security.issue_access_token(user_id=uuid.uuid4(), org_id=uuid.uuid4())
    tampered = token[:-3] + ("aaa" if not token.endswith("aaa") else "bbb")
    with pytest.raises(jwt.InvalidSignatureError):
        security.decode_token(tampered)
