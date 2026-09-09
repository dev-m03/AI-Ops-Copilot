"""Log schemas."""
from pydantic import BaseModel
from datetime import datetime


class LogCreate(BaseModel):
    """Log ingestion request."""
    api_key: str
    service: str
    level: str          # ERROR, WARN, INFO, DEBUG
    message: str
    idempotency_key: str | None = None
    """
    Optional caller-supplied key for exactly-once log delivery.
    If omitted the service auto-computes one from
    sha256(project_id:service:level:message:5-min-bucket).
    Two requests with the same resolved key within the same 5-minute
    window are treated as the same log entry — the second is a no-op.
    """


class LogResponse(BaseModel):
    """Log ingestion response."""
    id: str
    project_id: str
    incident_created: bool
    incident_id: str | None = None
    deduplicated: bool = False
    """True when this request was a duplicate and no new row was written."""
