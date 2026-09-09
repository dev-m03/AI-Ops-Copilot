"""
JWT authentication for AI-Ops Copilot.

Supabase projects signed with ECC (P-256) use ES256.
We verify tokens against Supabase's public JWKS endpoint so no shared
secret needs to be stored — only SUPABASE_URL (already required) is needed.

JWKS is fetched once on first request and cached in-process.
"""

import os

import httpx
from fastapi import Header, HTTPException
from jose import ExpiredSignatureError, JWTError, jwt

# Simple mutable cache — easier to mock/clear in tests than lru_cache
_jwks_cache: dict | None = None


def _get_jwks() -> dict:
    """
    Fetch the JWKS from Supabase once and cache it.
    Reads SUPABASE_URL at call time so env changes (e.g. in tests) are respected.
    """
    global _jwks_cache
    if _jwks_cache is not None:
        return _jwks_cache

    base_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    if not base_url:
        raise RuntimeError("SUPABASE_URL is not set")

    jwks_url = f"{base_url}/auth/v1/.well-known/jwks.json"
    try:
        resp = httpx.get(jwks_url, timeout=10)
        resp.raise_for_status()
        _jwks_cache = resp.json()
        return _jwks_cache
    except Exception as exc:
        raise RuntimeError(f"Failed to fetch JWKS from {jwks_url}: {exc}") from exc


def get_current_user(authorization: str = Header(...)) -> str:
    """
    Verify the Supabase JWT (ES256 / ECC P-256) and return the user_id.

    Raises HTTP 401 on:
    - missing / malformed Authorization header
    - invalid signature (forged token)
    - expired token
    - missing sub claim

    Raises HTTP 500 if SUPABASE_URL is not configured or JWKS fetch fails.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid auth header")

    token = authorization.removeprefix("Bearer ")

    try:
        jwks = _get_jwks()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    try:
        payload = jwt.decode(
            token,
            jwks,
            algorithms=["ES256"],
            audience="authenticated",
        )
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    user_id: str | None = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token: missing sub")

    return user_id
