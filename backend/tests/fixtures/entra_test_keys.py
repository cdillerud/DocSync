"""
Test fixtures for Entra ID token validation.

Provides a self-signed RSA keypair + token minter so the P1.H test suite
can exercise the full validation path with zero network calls.
"""
from __future__ import annotations

import base64
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def _b64url_uint(value: int) -> str:
    """Encode a Python int as base64url-encoded big-endian bytes (per RFC 7518)."""
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


@dataclass
class TestKeypair:
    kid: str
    private_pem: bytes
    public_pem: bytes
    jwk: Dict[str, Any]

    def as_jwks(self) -> Dict[str, Any]:
        return {"keys": [self.jwk]}


def make_test_keypair(kid: Optional[str] = None) -> TestKeypair:
    """Generate a fresh 2048-bit RSA keypair + JWK for tests."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_key = private_key.public_key()
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    numbers = public_key.public_numbers()
    jwk = {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": kid or uuid.uuid4().hex,
        "n": _b64url_uint(numbers.n),
        "e": _b64url_uint(numbers.e),
    }
    return TestKeypair(
        kid=jwk["kid"],
        private_pem=private_pem,
        public_pem=public_pem,
        jwk=jwk,
    )


def mint_token(
    *,
    keypair: TestKeypair,
    tenant_id: str,
    audience: str,
    issuer: Optional[str] = None,
    oid: Optional[str] = None,
    preferred_username: str = "test.user@example.com",
    email: Optional[str] = "test.user@example.com",
    roles: Optional[List[str]] = None,
    scp: Optional[str] = "access_as_users",
    expires_in: int = 3600,
    not_before_offset: int = 0,
    extra_claims: Optional[Dict[str, Any]] = None,
    override_alg: Optional[str] = None,
    omit_kid: bool = False,
) -> str:
    """Mint a signed JWT mimicking an Entra v2.0 access token.

    Defaults produce a user-delegated token (carries ``scp``); pass
    ``scp=None`` and ``roles=[...]`` for an app-only (service principal) token.
    ``override_alg`` and ``omit_kid`` are negative-test seams.
    """
    now = int(time.time())
    iss = issuer or f"https://login.microsoftonline.com/{tenant_id}/v2.0"
    payload: Dict[str, Any] = {
        "iss": iss,
        "aud": audience,
        "tid": tenant_id,
        "oid": oid or uuid.uuid4().hex,
        "preferred_username": preferred_username,
        "iat": now,
        "nbf": now + not_before_offset,
        "exp": now + expires_in,
    }
    if email:
        payload["email"] = email
    if roles is not None:
        payload["roles"] = roles
    if scp is not None:
        payload["scp"] = scp
    if extra_claims:
        payload.update(extra_claims)

    headers = {"alg": override_alg or "RS256", "typ": "JWT"}
    if not omit_kid:
        headers["kid"] = keypair.kid

    return jwt.encode(
        payload,
        keypair.private_pem,
        algorithm=override_alg or "RS256",
        headers=headers,
    )


def install_jwks_override(monkeypatch, keypair: TestKeypair) -> None:
    """Wire the test keypair into ``ENTRA_JWKS_OVERRIDE`` and reset the cache."""
    from services.entra_auth import reset_jwks_cache

    monkeypatch.setenv("ENTRA_JWKS_OVERRIDE", json.dumps(keypair.as_jwks()))
    reset_jwks_cache()


__all__ = [
    "TestKeypair",
    "make_test_keypair",
    "mint_token",
    "install_jwks_override",
]
