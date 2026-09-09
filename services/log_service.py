"""
Log ingestion and incident detection service.

Deduplication strategy
──────────────────────
1. Log-level dedup (retry storms):
   Each log gets a resolved idempotency_key:
     • Caller-supplied:  use as-is
     • Auto-computed:    sha256(project_id:service:level:message:5-min-bucket)
   Before inserting, we check logs.idempotency_key in the last DEDUP_WINDOW.
   If a match exists we return the existing row — no new DB write.

2. Incident-level dedup (threshold re-crossings):
   Before creating a new incident we look for any OPEN incident for the
   same (project_id, service).  If one exists we return its ID and bump
   occurrence_count (if that column exists) instead of duplicating.
"""

import hashlib
import logging
import math
from datetime import datetime, timedelta, timezone

from db.client import supabase
from schemas.logs import LogCreate, LogResponse

logger = logging.getLogger(__name__)

ERROR_THRESHOLD = 5
DEDUP_WINDOW_MINUTES = 5   # used for both log and error-count windows
BUCKET_SECONDS = 300        # 5-minute bucket for auto idempotency key


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def ingest_log(log: LogCreate) -> LogResponse:
    """
    Ingest a log entry idempotently, then create an incident if the
    ERROR_THRESHOLD is crossed and no open incident already exists.
    """
    # 1️⃣ Resolve project from API key
    project_res = (
        supabase.table("projects")
        .select("id, user_id")
        .eq("api_key", log.api_key)
        .single()
        .execute()
    )
    if not project_res.data:
        raise ValueError("Invalid API key")

    project_id: str = project_res.data["id"]

    # 2️⃣ Resolve idempotency key
    idem_key = _resolve_idempotency_key(log, project_id)

    # 3️⃣ Dedup check — is this a duplicate request?
    existing_log = _find_duplicate_log(idem_key)
    if existing_log:
        logger.info(
            "Duplicate log suppressed",
            extra={"context": {
                "idempotency_key": idem_key,
                "existing_log_id": existing_log["id"],
                "service": log.service,
            }},
        )
        return LogResponse(
            id=existing_log["id"],
            project_id=project_id,
            incident_created=False,
            incident_id=existing_log.get("incident_id"),
            deduplicated=True,
        )

    # 4️⃣ Insert new log row
    log_res = supabase.table("logs").insert({
        "project_id":       project_id,
        "service":          log.service,
        "level":            log.level,
        "message":          log.message,
        "idempotency_key":  idem_key,
        "created_at":       datetime.now(timezone.utc).isoformat(),
    }).execute()

    inserted_log_id: str = log_res.data[0]["id"]

    # 5️⃣ Incident creation (ERROR logs only)
    incident_id: str | None = None
    incident_created: bool = False
    if log.level == "ERROR":
        incident_id, incident_created = _check_and_create_incident(
            project_id, log.service, log.message
        )

    return LogResponse(
        id=inserted_log_id,
        project_id=project_id,
        incident_created=incident_created,
        incident_id=incident_id,
        deduplicated=False,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_idempotency_key(log: LogCreate, project_id: str) -> str:
    """
    Return the caller-supplied key or auto-compute one.

    The auto-computed key is sha256 of:
        project_id : service : level : message : <5-min epoch bucket>

    Two identical log lines within the same 5-minute window produce the
    same key, making retries within that window no-ops.
    """
    if log.idempotency_key:
        return log.idempotency_key

    now_epoch = datetime.now(timezone.utc).timestamp()
    bucket = math.floor(now_epoch / BUCKET_SECONDS) * BUCKET_SECONDS
    raw = f"{project_id}:{log.service}:{log.level}:{log.message}:{bucket}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _find_duplicate_log(idem_key: str) -> dict | None:
    """
    Look for an existing log row with the same idempotency key written
    within the last DEDUP_WINDOW_MINUTES.  Returns the row or None.
    """
    since = (
        datetime.now(timezone.utc) - timedelta(minutes=DEDUP_WINDOW_MINUTES)
    ).isoformat()

    try:
        res = (
            supabase.table("logs")
            .select("id, incident_id")
            .eq("idempotency_key", idem_key)
            .gte("created_at", since)
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else None
    except Exception:
        logger.exception(
            "Dedup check failed — proceeding with insert",
            extra={"context": {"idempotency_key": idem_key}},
        )
        return None  # fail open: don't block ingestion if dedup query errors


def _check_and_create_incident(
    project_id: str, service: str, message: str
) -> tuple[str | None, bool]:
    """
    Create an incident only when:
      a) the ERROR threshold has been crossed in the last window, AND
      b) no OPEN incident already exists for this (project_id, service).

    If an open incident already exists, bump its occurrence_count instead
    of creating a duplicate.

    Returns (incident_id | None, was_created).
    """
    since = (
        datetime.now(timezone.utc) - timedelta(minutes=DEDUP_WINDOW_MINUTES)
    ).isoformat()

    # Count recent errors
    logs_res = (
        supabase.table("logs")
        .select("id")
        .eq("project_id", project_id)
        .eq("service", service)
        .eq("level", "ERROR")
        .gte("created_at", since)
        .execute()
    )

    if len(logs_res.data) < ERROR_THRESHOLD:
        return None, False  # threshold not crossed yet

    # Check for an existing open incident
    existing_res = (
        supabase.table("incidents")
        .select("id, occurrence_count")
        .eq("project_id", project_id)
        .eq("service", service)
        .eq("status", "open")
        .limit(1)
        .execute()
    )

    if existing_res.data:
        # Incident already open — bump occurrence_count if the column exists
        existing = existing_res.data[0]
        existing_id: str = existing["id"]
        current_count: int = existing.get("occurrence_count") or 1

        try:
            supabase.table("incidents").update(
                {"occurrence_count": current_count + 1}
            ).eq("id", existing_id).execute()
        except Exception:
            # Column may not exist yet — log a warning but don't fail
            logger.warning(
                "Could not bump occurrence_count (column may not exist)",
                extra={"context": {
                    "incident_id": existing_id,
                    "project_id": project_id,
                    "service": service,
                }},
            )

        logger.info(
            "Open incident already exists — skipped duplicate creation",
            extra={"context": {
                "incident_id": existing_id,
                "project_id": project_id,
                "service": service,
            }},
        )
        return existing_id, False   # found existing — NOT a new creation

    # No open incident — create one
    try:
        incident_res = supabase.table("incidents").insert({
            "project_id":       project_id,
            "service":          service,
            "summary":          message,
            "severity":         "high",
            "status":           "open",
            "occurrence_count": 1,
            "created_at":       datetime.now(timezone.utc).isoformat(),
        }).execute()
        return incident_res.data[0]["id"], True
    except Exception:
        logger.exception(
            "Failed to create incident",
            extra={"context": {"project_id": project_id, "service": service}},
        )
        return None, False
