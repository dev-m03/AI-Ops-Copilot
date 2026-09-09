"""Project management routes."""
import logging

from fastapi import APIRouter, Depends, HTTPException

from db.auth import get_current_user
from schemas.projects import ProjectCreate, ProjectResponse
from services.project_service import create_project, get_project, list_projects

router = APIRouter(prefix="/projects", tags=["projects"])
logger = logging.getLogger(__name__)


@router.post("", response_model=ProjectResponse)
def create_new_project(
    data: ProjectCreate,
    user_id: str = Depends(get_current_user),
):
    """Create a new project."""
    try:
        return create_project(user_id, data)
    except Exception:
        logger.exception(
            "Unexpected error creating project",
            extra={"context": {"user_id": user_id}},
        )
        raise HTTPException(status_code=500, detail="Failed to create project")


@router.get("", response_model=list[ProjectResponse])
def list_user_projects(user_id: str = Depends(get_current_user)):
    """List all projects for current user."""
    try:
        return list_projects(user_id)
    except Exception:
        logger.exception(
            "Unexpected error listing projects",
            extra={"context": {"user_id": user_id}},
        )
        raise HTTPException(status_code=500, detail="Failed to fetch projects")


@router.get("/{project_id}", response_model=ProjectResponse)
def get_user_project(
    project_id: str,
    user_id: str = Depends(get_current_user),
):
    """Get specific project details."""
    try:
        return get_project(user_id, project_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Project not found")
    except Exception:
        logger.exception(
            "Unexpected error fetching project",
            extra={"context": {"user_id": user_id, "project_id": project_id}},
        )
        raise HTTPException(status_code=500, detail="Failed to fetch project")
