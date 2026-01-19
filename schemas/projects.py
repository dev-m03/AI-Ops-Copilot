"""Project schemas."""
from pydantic import BaseModel
from datetime import datetime

class ProjectCreate(BaseModel):
    """Project creation request."""
    name: str


class ProjectResponse(BaseModel):
    """Project response."""
    id: str
    name: str
    api_key: str
    created_at: datetime
