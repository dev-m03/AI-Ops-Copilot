from app.supabase.client import supabase

def get_incident(user_id: str, incident_id: str):
    # 1. Fetch incident
    incident_res = (
        supabase
        .table("incidents")
        .select("*")
        .eq("id", incident_id)
        .single()
        .execute()
    )

    if not incident_res.data:
        raise ValueError("incident not found")

    incident = incident_res.data

    # 2. Fetch project
    project_res = (
        supabase
        .table("projects")
        .select("*")
        .eq("id", incident["project_id"])
        .single()
        .execute()
    )

    if not project_res.data:
        raise ValueError("project not found")

    project = project_res.data

    # 3. AUTHORIZE
    if project["user_id"] != user_id:
        raise ValueError("unauthorized")

    return incident
