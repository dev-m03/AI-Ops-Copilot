from fastapi import APIRouter, Depends
from db.auth import get_current_user
from db.client import supabase

router = APIRouter(prefix="/incidents", tags=["incidents"])

@router.get("")
def list_incidents(user_id: str = Depends(get_current_user)):
    res = (
        supabase
        .table("incidents")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )
    return res.data
