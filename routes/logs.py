"""Log ingestion route."""
from fastapi import APIRouter, HTTPException
from app.schemas.logs import LogCreate, LogResponse
from app.services.log_service import ingest_log

router = APIRouter(prefix="/logs", tags=["logs"])


@router.post("", response_model=LogResponse)
def create_log(log: LogCreate):
    """Ingest a new log entry."""
    try:
        return ingest_log(log)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to ingest log")
