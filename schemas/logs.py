"""Log schemas."""
from pydantic import BaseModel
from datetime import datetime

class LogCreate(BaseModel):
    """Log ingestion request."""
    api_key: str
    service: str
    level: str  # ERROR, WARN, INFO, DEBUG
    message: str


class LogResponse(BaseModel):
    """Log ingestion response."""
    id: str
    project_id: str
    incident_created: bool
    incident_id: str | None = None
