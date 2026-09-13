"""
Tests for JWT authentication in db/auth.py (ES256 / ECC P-256).

Covers
------
- Valid ES256 token (signed with test key, JWKS mocked) → 200
- Token signed with the wrong / attacker key             → 401
- Expired token                                          → 401
- Missing Authorization header                           → 422 (FastAPI validation)
- Malformed header (e.g. "Token …" instead of "Bearer …")→ 401
- Token with no ``sub`` claim                            → 401
"""
# ── Env setup — MUST precede ALL project imports ─────────────────────────────
import os

os.environ.setdefault("SUPABASE_URL", "https://fake.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "fake-key")

# ── stdlib / third-party ──────────────────────────────────────────────────────
import time
from base64 import urlsafe_b64encode
from unittest.mock import patch

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt

# ── Project imports (after env is set) ───────────────────────────────────────
import db.auth as auth_module

# ── Key material — generated once per test-session ───────────────────────────

_REAL_PRIV = ec.generate_private_key(ec.SECP256R1(), default_backend())
_REAL_PUB = _REAL_PRIV.public_key()
_FAKE_PRIV = ec.generate_private_key(ec.SECP256R1(), default_backend())  # "attacker" key


def _priv_pem(key) -> str:
    return key.private_bytes(
        Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption()
    ).decode()


def _pub_to_jwk(pub_key) -> dict:
    """Convert EC public key → JWK dict compatible with python-jose."""
    nums = pub_key.public_numbers()

    def b64url(n: int) -> str:
        return urlsafe_b64encode(n.to_bytes(32, "big")).rstrip(b"=").decode()

    return {
        "kty": "EC",
        "crv": "P-256",
        "x": b64url(nums.x),
        "y": b64url(nums.y),
        "alg": "ES256",
        "use": "sig",
    }


_REAL_JWKS = {"keys": [_pub_to_jwk(_REAL_PUB)]}


# ── Token helpers ─────────────────────────────────────────────────────────────

def _make_token(sub: str | None, priv_key=None, exp_offset: int = 3600) -> str:
    """Sign an ES256 JWT with the given private key (defaults to the real key)."""
    if priv_key is None:
        priv_key = _REAL_PRIV
    now = int(time.time())
    claims: dict = {"aud": "authenticated", "iat": now, "exp": now + exp_offset}
    if sub is not None:
        claims["sub"] = sub
    return jose_jwt.encode(claims, _priv_pem(priv_key), algorithm="ES256")


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── Minimal FastAPI app wired to our dependency ───────────────────────────────

_app = FastAPI()


@_app.get("/whoami")
def whoami(user_id: str = Depends(auth_module.get_current_user)):
    return {"user_id": user_id}


_client = TestClient(_app, raise_server_exceptions=False)


# ── Helper that clears the JWKS in-process cache before each test ─────────────

def _reset_jwks_cache():
    auth_module._jwks_cache = None


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_valid_token_accepted():
    """Correctly signed token using the real key → 200 with the expected user_id."""
    _reset_jwks_cache()
    with patch.object(auth_module, "_get_jwks", return_value=_REAL_JWKS):
        res = _client.get("/whoami", headers=_bearer(_make_token("user-abc")))
    assert res.status_code == 200
    assert res.json()["user_id"] == "user-abc"


def test_wrong_key_rejected():
    """Token signed by an attacker's private key must be rejected (401)."""
    _reset_jwks_cache()
    with patch.object(auth_module, "_get_jwks", return_value=_REAL_JWKS):
        forged = _make_token("user-abc", priv_key=_FAKE_PRIV)
        res = _client.get("/whoami", headers=_bearer(forged))
    assert res.status_code == 401
    assert "Invalid token" in res.json()["detail"]


def test_expired_token_rejected():
    """Token whose ``exp`` is in the past → 401 with 'expired' detail."""
    _reset_jwks_cache()
    with patch.object(auth_module, "_get_jwks", return_value=_REAL_JWKS):
        expired = _make_token("user-abc", exp_offset=-10)   # expired 10 s ago
        res = _client.get("/whoami", headers=_bearer(expired))
    assert res.status_code == 401
    # Auth module raises "Token has expired" for ExpiredSignatureError
    assert "expired" in res.json()["detail"].lower()


def test_missing_authorization_header():
    """No Authorization header → 422 (FastAPI required-header validation)."""
    res = _client.get("/whoami")
    assert res.status_code == 422


def test_malformed_authorization_scheme():
    """'Token xyz' instead of 'Bearer xyz' → 401 (wrong scheme)."""
    _reset_jwks_cache()
    with patch.object(auth_module, "_get_jwks", return_value=_REAL_JWKS):
        token = _make_token("user-abc")
        res = _client.get("/whoami", headers={"Authorization": f"Token {token}"})
    assert res.status_code == 401
    assert "Invalid auth header" in res.json()["detail"]


def test_missing_sub_claim_rejected():
    """Validly signed token that has no ``sub`` claim → 401."""
    _reset_jwks_cache()
    with patch.object(auth_module, "_get_jwks", return_value=_REAL_JWKS):
        token = _make_token(sub=None)   # sub omitted from claims
        res = _client.get("/whoami", headers=_bearer(token))
    assert res.status_code == 401
    assert "missing sub" in res.json()["detail"]
