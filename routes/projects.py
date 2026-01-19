"""Project management routes."""
from fastapi import APIRouter, Depends, HTTPException
from app.schemas.projects import ProjectCreate, ProjectResponse
from app.services.project_service import create_project, list_projects, get_project
from app.supabase.auth import get_current_user

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectResponse)
def create_new_project(
    data: ProjectCreate,
    user_id: str = Depends(get_current_user)
):
    """Create a new project."""
    try:
        return create_project(user_id, data)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to create project")


@router.get("", response_model=list[ProjectResponse])
def list_user_projects(user_id: str = Depends(get_current_user)):
    """List all projects for current user."""
    try:
        return list_projects(user_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to fetch projects")


@router.get("/{project_id}", response_model=ProjectResponse)
def get_user_project(
    project_id: str,
    user_id: str = Depends(get_current_user)
):
    """Get specific project details."""
    try:
        return get_project(user_id, project_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Project not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to fetch project")
