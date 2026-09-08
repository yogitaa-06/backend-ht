"""Cryptographic and cache behavior tests for Supabase access-token verification."""

import time
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from jwt.utils import base64url_encode, to_base64url_uint

from app.auth.verifier import (
    InvalidAccessTokenError,
    JwksDocument,
    JwksUnavailableError,
    SupabaseJwtVerifier,
)
from app.core.config import Settings

pytestmark = pytest.mark.anyio


class FakeJwksFetcher:
    """Return deterministic documents without reaching Supabase."""

    def __init__(self, *responses: JwksDocument | Exception) -> None:
        self.responses = list(responses)
        self.calls = 0

    async def __call__(self, _: str) -> JwksDocument:
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture(scope="module")
def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def other_rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def ec_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def auth_settings() -> Settings:
    return Settings(_env_file=None, supabase_url="https://example.supabase.co")


def claims(**overrides: object) -> dict[str, object]:
    now = int(time.time())
    values: dict[str, object] = {
        "sub": str(uuid4()),
        "iss": "https://example.supabase.co/auth/v1",
        "aud": "authenticated",
        "iat": now,
        "exp": now + 300,
        "email": "employee@example.com",
        "session_id": str(uuid4()),
        "role": "authenticated",
    }
    values.update(overrides)
    return values


def encode_token(
    key: Any,
    algorithm: str,
    token_claims: Mapping[str, object],
    *,
    kid: str = "key-1",
) -> str:
    return jwt.encode(dict(token_claims), key, algorithm=algorithm, headers={"kid": kid})


def rsa_jwk(key: rsa.RSAPrivateKey, *, kid: str = "key-1") -> dict[str, object]:
    numbers = key.public_key().public_numbers()
    return {
        "kty": "RSA",
        "kid": kid,
        "use": "sig",
        "alg": "RS256",
        "n": to_base64url_uint(numbers.n).decode(),
        "e": to_base64url_uint(numbers.e).decode(),
    }


def ec_jwk(key: ec.EllipticCurvePrivateKey, *, kid: str = "key-1") -> dict[str, object]:
    numbers = key.public_key().public_numbers()
    return {
        "kty": "EC",
        "kid": kid,
        "use": "sig",
        "alg": "ES256",
        "crv": "P-256",
        "x": base64url_encode(numbers.x.to_bytes(32, "big")).decode(),
        "y": base64url_encode(numbers.y.to_bytes(32, "big")).decode(),
    }


async def test_valid_es256_token_is_accepted(ec_key: ec.EllipticCurvePrivateKey) -> None:
    fetcher = FakeJwksFetcher({"keys": [ec_jwk(ec_key)]})
    verifier = SupabaseJwtVerifier(auth_settings(), fetcher=fetcher)
    subject = uuid4()

    verified = await verifier.verify(encode_token(ec_key, "ES256", claims(sub=str(subject))))

    assert verified.subject == subject
    assert verified.email == "employee@example.com"


async def test_valid_rs256_token_is_accepted(rsa_key: rsa.RSAPrivateKey) -> None:
    verifier = SupabaseJwtVerifier(
        auth_settings(), fetcher=FakeJwksFetcher({"keys": [rsa_jwk(rsa_key)]})
    )

    verified = await verifier.verify(encode_token(rsa_key, "RS256", claims()))

    assert verified.provider_role == "authenticated"


@pytest.mark.parametrize(
    "claim_changes",
    [
        {"exp": int(time.time()) - 10},
        {"iss": "https://attacker.example/auth/v1"},
        {"aud": "wrong-audience"},
        {"sub": None},
        {"sub": "not-a-uuid"},
    ],
    ids=["expired", "wrong-issuer", "wrong-audience", "missing-sub", "invalid-sub-uuid"],
)
async def test_invalid_claims_are_rejected(
    rsa_key: rsa.RSAPrivateKey,
    claim_changes: dict[str, object],
) -> None:
    token_claims = claims(**claim_changes)
    if claim_changes.get("sub", object()) is None:
        token_claims.pop("sub")
    verifier = SupabaseJwtVerifier(
        auth_settings(), fetcher=FakeJwksFetcher({"keys": [rsa_jwk(rsa_key)]})
    )

    with pytest.raises(InvalidAccessTokenError):
        await verifier.verify(encode_token(rsa_key, "RS256", token_claims))


async def test_invalid_signature_is_rejected(
    rsa_key: rsa.RSAPrivateKey,
    other_rsa_key: rsa.RSAPrivateKey,
) -> None:
    verifier = SupabaseJwtVerifier(
        auth_settings(), fetcher=FakeJwksFetcher({"keys": [rsa_jwk(rsa_key)]})
    )

    with pytest.raises(InvalidAccessTokenError):
        await verifier.verify(encode_token(other_rsa_key, "RS256", claims()))


@pytest.mark.parametrize("algorithm", ["HS256", "none"])
async def test_unsafe_algorithms_are_rejected_without_fetching_keys(algorithm: str) -> None:
    fetcher = FakeJwksFetcher({"keys": []})
    verifier = SupabaseJwtVerifier(auth_settings(), fetcher=fetcher)
    key = "a-test-shared-secret-that-is-not-used" if algorithm == "HS256" else ""

    with pytest.raises(InvalidAccessTokenError):
        await verifier.verify(encode_token(key, algorithm, claims()))

    assert fetcher.calls == 0


async def test_malformed_token_is_rejected_without_fetching_keys() -> None:
    fetcher = FakeJwksFetcher({"keys": []})
    verifier = SupabaseJwtVerifier(auth_settings(), fetcher=fetcher)

    with pytest.raises(InvalidAccessTokenError):
        await verifier.verify("not-a-jwt")

    assert fetcher.calls == 0


async def test_unknown_kid_refreshes_and_accepts_rotated_key(
    rsa_key: rsa.RSAPrivateKey,
    other_rsa_key: rsa.RSAPrivateKey,
) -> None:
    fetcher = FakeJwksFetcher(
        {"keys": [rsa_jwk(rsa_key, kid="old")]},
        {"keys": [rsa_jwk(other_rsa_key, kid="new")]},
    )
    verifier = SupabaseJwtVerifier(auth_settings(), fetcher=fetcher)

    verified = await verifier.verify(encode_token(other_rsa_key, "RS256", claims(), kid="new"))

    assert verified.subject
    assert fetcher.calls == 2


async def test_unknown_kid_after_refresh_is_rejected(rsa_key: rsa.RSAPrivateKey) -> None:
    document: JwksDocument = {"keys": [rsa_jwk(rsa_key, kid="known")]}
    fetcher = FakeJwksFetcher(document, document)
    verifier = SupabaseJwtVerifier(auth_settings(), fetcher=fetcher)

    with pytest.raises(InvalidAccessTokenError):
        await verifier.verify(encode_token(rsa_key, "RS256", claims(), kid="unknown"))

    assert fetcher.calls == 2


async def test_jwks_retrieval_failure_is_distinct_and_safe(rsa_key: rsa.RSAPrivateKey) -> None:
    verifier = SupabaseJwtVerifier(
        auth_settings(), fetcher=FakeJwksFetcher(OSError("private network detail"))
    )

    with pytest.raises(JwksUnavailableError) as exc_info:
        await verifier.verify(encode_token(rsa_key, "RS256", claims()))

    assert str(exc_info.value) == ""


async def test_cache_prevents_repeated_jwks_fetches(rsa_key: rsa.RSAPrivateKey) -> None:
    fetcher = FakeJwksFetcher({"keys": [rsa_jwk(rsa_key)]})
    verifier = SupabaseJwtVerifier(auth_settings(), fetcher=fetcher)

    await verifier.verify(encode_token(rsa_key, "RS256", claims()))
    await verifier.verify(encode_token(rsa_key, "RS256", claims()))

    assert fetcher.calls == 1


async def test_provider_role_is_identity_metadata_not_application_authorization(
    rsa_key: rsa.RSAPrivateKey,
) -> None:
    verifier = SupabaseJwtVerifier(
        auth_settings(), fetcher=FakeJwksFetcher({"keys": [rsa_jwk(rsa_key)]})
    )

    verified = await verifier.verify(encode_token(rsa_key, "RS256", claims(role="service_role")))

    assert verified.provider_role == "service_role"
    assert not hasattr(verified, "role")
