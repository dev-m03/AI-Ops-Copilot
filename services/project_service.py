"""Project management service."""
from datetime import datetime
from supabase.client import supabase
from utils.api_key import generate_api_key
from schemas.projects import ProjectCreate, ProjectResponse


def create_project(user_id: str, data: ProjectCreate) -> ProjectResponse:
    """Create a new project for user."""
    api_key = generate_api_key()
    
    res = supabase.table("projects").insert({
        "user_id": user_id,
        "name": data.name,
        "api_key": api_key,
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    
    project = res.data[0]
    return ProjectResponse(
        id=project["id"],
        name=project["name"],
        api_key=api_key,
        created_at=project["created_at"]
    )


def list_projects(user_id: str) -> list[ProjectResponse]:
    """List all projects for a user."""
    res = supabase.table("projects").select("*").eq("user_id", user_id).execute()
    
    return [
        ProjectResponse(
            id=p["id"],
            name=p["name"],
            api_key=p["api_key"],
            created_at=p["created_at"]
        )
        for p in res.data
    ]


def get_project(user_id: str, project_id: str) -> ProjectResponse:
    """Get a specific project."""
    res = supabase.table("projects").select("*").eq("id", project_id).eq("user_id", user_id).single().execute()
    
    if not res.data:
        raise ValueError("Project not found")
    
    p = res.data
    return ProjectResponse(
        id=p["id"],
        name=p["name"],
        api_key=p["api_key"],
        created_at=p["created_at"]
    )
