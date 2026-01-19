from fastapi import APIRouter, Depends
from asupabase.auth import get_current_user
from supabase.client import supabase

router = APIRouter(prefix="/incidents", tags=["incidents"])


@router.get("")
def list_incidents(user_id: str = Depends(get_current_user)):
    """
    Return only incidents belonging to the current user.
    """

    # 1️⃣ Fetch user projects
    projects_res = (
        supabase
        .table("projects")
        .select("id")
        .eq("user_id", user_id)
        .execute()
    )

    project_ids = [p["id"] for p in projects_res.data]

    if not project_ids:
        return []

    # 2️⃣ Fetch incidents for those projects only
    incidents_res = (
        supabase
        .table("incidents")
        .select("*")
        .in_("project_id", project_ids)
        .order("created_at", desc=True)
        .execute()
    )

    return incidents_res.data
