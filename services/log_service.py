"""Log ingestion and incident detection service."""
from datetime import datetime, timedelta
from supabase.client import supabase
from schemas.logs import LogCreate, LogResponse

ERROR_THRESHOLD = 5

def ingest_log(log: LogCreate) -> LogResponse:
    """Ingest a log and create incident if threshold reached."""
    # Get project by API key
    project_res = supabase.table("projects").select("id, user_id").eq("api_key", log.api_key).single().execute()
    
    if not project_res.data:
        raise ValueError("Invalid API key")
    
    project_id = project_res.data["id"]
    
    # Insert log
    log_res = supabase.table("logs").insert({
        "project_id": project_id,
        "service": log.service,
        "level": log.level,
        "message": log.message,
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    
    # Check if incident should be created
    incident_id = None
    if log.level == "ERROR":
        incident_id = _check_and_create_incident(project_id, log.service, log.message)
    
    return LogResponse(
        id=log_res.data[0]["id"],
        project_id=project_id,
        incident_created=incident_id is not None,
        incident_id=incident_id
    )


def _check_and_create_incident(project_id: str, service: str, message: str) -> str | None:
    """Check error threshold and create incident if needed."""
    since = (datetime.utcnow() - timedelta(minutes=5)).isoformat()
    
    logs_res = supabase.table("logs").select("*").eq("project_id", project_id).eq("service", service).eq("level", "ERROR").gte("created_at", since).execute()
    
    if len(logs_res.data) >= ERROR_THRESHOLD:
        incident_res = supabase.table("incidents").insert({
            "project_id": project_id,
            "service": service,
            "summary": message,
            "severity": "high",
            "status": "open",
            "created_at": datetime.utcnow().isoformat()
        }).execute()
        return incident_res.data[0]["id"]
    
    return None
