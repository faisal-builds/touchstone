"""Security primitives for the control plane (ADR-009).

Two authentication planes:

  * **API keys** — for programmatic SDK/API access. We generate a high-entropy
    secret, show it to the user exactly once, and persist only its Argon2id
    hash plus a non-secret lookup prefix. A leaked database can never be used to
    authenticate because the plaintext key is unrecoverable.

  * **JWT** — short-lived bearer tokens for the human dashboard, signed with
    HS256 in V1 (swap to RS256/JWKS when the auth service is split out).

Key format:  ``tsk_<keyid>_<secret>``
  * ``tsk``    : product prefix (greppable, makes accidental commits detectable)
  * ``keyid``  : 12-char public identifier, indexed for O(1) lookup
  * ``secret`` : 43-char url-safe secret, never stored in plaintext
"""

from __future__ import annotations

import datetime as _dt
import hmac
import secrets
import uuid
from dataclasses import dataclass

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from .config import Settings

_KEY_ID_BYTES = 9
_SECRET_BYTES = 32
# Base62 alphabet deliberately EXCLUDES the '_' key delimiter and '-' so a
# generated key never collides with the separator. (base64url contains '_',
# which would make `tsk_<id>_<secret>` ambiguous to parse — a real auth bug.)
_B62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def _b62(raw: bytes) -> str:
    n = int.from_bytes(raw, "big")
    if n == 0:
        return _B62[0]
    out: list[str] = []
    base = len(_B62)
    while n:
        n, rem = divmod(n, base)
        out.append(_B62[rem])
    return "".join(reversed(out))


@dataclass(frozen=True)
class GeneratedApiKey:
    """Returned to the caller exactly once on key creation."""

    key_id: str  # public, stored in plaintext (indexed)
    plaintext: str  # full key, shown once, never persisted
    secret_hash: str  # Argon2id hash of the secret, persisted


class SecurityService:
    """Stateless cryptographic operations. Constructed from Settings."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._hasher = PasswordHasher(
            time_cost=settings.argon2_time_cost,
            memory_cost=settings.argon2_memory_cost,
            parallelism=settings.argon2_parallelism,
        )
        # Precomputed once; used by dummy_verify() for constant-time login.
        self._dummy_hash = self._hasher.hash("touchstone-dummy-password")

    # --- API keys -------------------------------------------------------------
    def generate_api_key(self) -> GeneratedApiKey:
        key_id = _b62(secrets.token_bytes(_KEY_ID_BYTES))
        secret = _b62(secrets.token_bytes(_SECRET_BYTES))
        plaintext = f"{self._settings.api_key_prefix}_{key_id}_{secret}"
        secret_hash = self._hasher.hash(secret)
        return GeneratedApiKey(key_id=key_id, plaintext=plaintext, secret_hash=secret_hash)

    def parse_api_key(self, presented: str) -> tuple[str, str] | None:
        """Split a presented key into (key_id, secret). Returns None if malformed."""
        parts = presented.split("_")
        if len(parts) != 3 or parts[0] != self._settings.api_key_prefix:
            return None
        _, key_id, secret = parts
        if not key_id or not secret:
            return None
        return key_id, secret

    def verify_api_key_secret(self, secret: str, secret_hash: str) -> bool:
        try:
            return self._hasher.verify(secret_hash, secret)
        except VerifyMismatchError:
            return False
        except Exception:  # malformed hash, etc. -> deny
            return False

    def needs_rehash(self, secret_hash: str) -> bool:
        """True if Argon2 params changed and the stored hash should be upgraded."""
        return self._hasher.check_needs_rehash(secret_hash)

    def rehash_secret(self, secret: str) -> str:
        return self._hasher.hash(secret)

    # --- JWT ------------------------------------------------------------------
    def issue_access_token(self, *, user_id: uuid.UUID, org_id: uuid.UUID) -> str:
        now = _dt.datetime.now(_dt.UTC)
        claims = {
            "sub": str(user_id),
            "org": str(org_id),
            "type": "access",
            "iat": now,
            "exp": now + _dt.timedelta(seconds=self._settings.jwt_access_ttl_seconds),
            "jti": str(uuid.uuid4()),
        }
        return jwt.encode(
            claims,
            self._settings.jwt_secret.get_secret_value(),
            algorithm=self._settings.jwt_algorithm,
        )

    def decode_token(self, token: str) -> dict:
        return jwt.decode(
            token,
            self._settings.jwt_secret.get_secret_value(),
            algorithms=[self._settings.jwt_algorithm],
        )

    def issue_service_token(self, *, service: str, ttl_seconds: int = 60) -> str:
        """Mint a short-lived service-to-service token.

        Used to authenticate internal calls between Touchstone services (e.g. the
        reward-hacking-detector calling the control-plane's auth introspection
        endpoint). Signed with the shared secret; verified by ``decode_token``
        and a ``type == "service"`` check.
        """
        now = _dt.datetime.now(_dt.UTC)
        claims = {
            "sub": service,
            "type": "service",
            "iat": now,
            "exp": now + _dt.timedelta(seconds=ttl_seconds),
            "jti": str(uuid.uuid4()),
        }
        return jwt.encode(
            claims,
            self._settings.jwt_secret.get_secret_value(),
            algorithm=self._settings.jwt_algorithm,
        )

    # --- User passwords -------------------------------------------------------
    def hash_password(self, password: str) -> str:
        """Argon2id hash for a user password (dashboard/SSO-less auth)."""
        return self._hasher.hash(password)

    def dummy_verify(self) -> None:
        """Run a verify against a throwaway hash so that login timing is the same
        whether or not the email exists (mitigates user enumeration)."""
        try:
            self._hasher.verify(self._dummy_hash, "not-the-password")
        except Exception:  # noqa: S110 — deliberate: equalize timing, ignore result
            pass

    def verify_password(self, password: str, password_hash: str) -> bool:
        try:
            return self._hasher.verify(password_hash, password)
        except VerifyMismatchError:
            return False
        except Exception:  # malformed hash -> deny
            return False

    # --- Constant-time helpers ------------------------------------------------
    @staticmethod
    def constant_time_equals(a: str, b: str) -> bool:
        return hmac.compare_digest(a.encode(), b.encode())
