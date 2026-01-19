from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader
from app.supabase.client import supabase

# -------- JWT (Human auth) --------
jwt_scheme = HTTPBearer(auto_error=True)

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(jwt_scheme),
):
    token = credentials.credentials
    # v1: trust Supabase JWT (can verify later)
    return {
        "user_id": "authenticated-user",
        "token": token
    }

# -------- API KEY (Machine auth) --------
api_key_scheme = APIKeyHeader(
    name="X-API-Key",
    auto_error=True
)

def require_api_key(
    api_key: str = Depends(api_key_scheme)
):
    res = supabase.table("projects") \
        .select("id") \
        .eq("api_key", api_key) \
        .single() \
        .execute()

    if not res.data:
        raise HTTPException(status_code=401, detail="Invalid API key")

    return res.data["id"]  # project_id
