from fastapi import Header, HTTPException
import base64
import json

def get_current_user(authorization: str = Header(...)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid auth header")

    token = authorization.replace("Bearer ", "")

    try:
        # Decode JWT payload WITHOUT verification
        payload_part = token.split(".")[1]
        payload_part += "=" * (-len(payload_part) % 4)  # padding

        payload = json.loads(base64.urlsafe_b64decode(payload_part))
        user_id = payload.get("sub")

        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")

        return user_id

    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")
