"""
Tests for JWT authentication in db/auth.py (ES256 / ECC P-256).

IMPORTANT: env vars MUST be set before importing db.auth because _get_jwks
reads SUPABASE_URL at call time but the module is imported only once.
"""

# ── env setup — MUST come before any project imports ─────────────────────────
import os
os.environ["SUPABASE_URL"] = "https://fake.supabase.co"

# ── stdlib / third-party ──────────────────────────────────────────────────────
import time
from base64 import urlsafe_b64encode
from unittest.mock import patch

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import (
    Encoding, NoEncryption, PrivateFormat,
)
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt

# ── project imports (after env is set) ────────────────────────────────────────
import db.auth as auth_module

# ── Generate two EC key pairs ─────────────────────────────────────────────────
_REAL_PRIV = ec.generate_private_key(ec.SECP256R1(), default_backend())
_REAL_PUB  = _REAL_PRIV.public_key()
_FAKE_PRIV = ec.generate_private_key(ec.SECP256R1(), default_backend())


def _priv_pem(key) -> str:
    return key.private_bytes(
        Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption()
    ).decode()


def _pub_to_jwk(pub_key) -> dict:
    """Convert an EC public key to a JWK dict that python-jose understands."""
    nums = pub_key.public_numbers()

    def b64url(n: int) -> str:
        b = n.to_bytes(32, "big")          # P-256 coords are always 32 bytes
        return urlsafe_b64encode(b).rstrip(b"=").decode()

    return {
        "kty": "EC",
        "crv": "P-256",
        "x": b64url(nums.x),
        "y": b64url(nums.y),
        "alg": "ES256",
        "use": "sig",
    }


_REAL_JWKS = {"keys": [_pub_to_jwk(_REAL_PUB)]}


# ── helpers ───────────────────────────────────────────────────────────────────

def make_token(sub: str | None, priv_key=None, exp_offset: int = 3600) -> str:
    """Sign an ES256 JWT with the given private key (defaults to real key)."""
    if priv_key is None:
        priv_key = _REAL_PRIV
    now = int(time.time())
    claims: dict = {"aud": "authenticated", "iat": now, "exp": now + exp_offset}
    if sub is not None:
        claims["sub"] = sub
    return jose_jwt.encode(claims, _priv_pem(priv_key), algorithm="ES256")


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── minimal FastAPI app driven by TestClient ───────────────────────────────────

app = FastAPI()

@app.get("/whoami")
def whoami(user_id: str = Depends(auth_module.get_current_user)):
    return {"user_id": user_id}

client = TestClient(app, raise_server_exceptions=False)


# ── tests ──────────────────────────────────────────────────────────────────────

def test_valid_token_accepted():
    """Correctly signed token from the real key → 200 with user_id."""
    with patch.object(auth_module, "_get_jwks", return_value=_REAL_JWKS):
        res = client.get("/whoami", headers=auth_header(make_token("user-abc")))
    assert res.status_code == 200
    assert res.json()["user_id"] == "user-abc"


def test_forged_token_rejected():
    """Token signed by attacker's key → 401 (signature mismatch)."""
    with patch.object(auth_module, "_get_jwks", return_value=_REAL_JWKS):
        forged = make_token("user-abc", priv_key=_FAKE_PRIV)
        res = client.get("/whoami", headers=auth_header(forged))
    assert res.status_code == 401
    assert "Invalid token" in res.json()["detail"]


def test_expired_token_rejected():
    """Token with exp in the past → 401."""
    with patch.object(auth_module, "_get_jwks", return_value=_REAL_JWKS):
        expired = make_token("user-abc", exp_offset=-10)
        res = client.get("/whoami", headers=auth_header(expired))
    assert res.status_code == 401


def test_missing_sub_rejected():
    """Validly signed token with no sub claim → 401."""
    with patch.object(auth_module, "_get_jwks", return_value=_REAL_JWKS):
        token = make_token(None)     # sub=None → claim omitted
        res = client.get("/whoami", headers=auth_header(token))
    assert res.status_code == 401


def test_missing_authorization_header():
    """No Authorization header → 422 (FastAPI required-header validation)."""
    res = client.get("/whoami")
    assert res.status_code == 422


def test_wrong_scheme_rejected():
    """'Token xyz' instead of 'Bearer xyz' → 401."""
    with patch.object(auth_module, "_get_jwks", return_value=_REAL_JWKS):
        token = make_token("user-abc")
        res = client.get("/whoami", headers={"Authorization": f"Token {token}"})
    assert res.status_code == 401
