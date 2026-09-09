"""
Log ingestion and incident detection service.

Detection vs. AI — important distinction
─────────────────────────────────────────
  Incident DETECTION is purely threshold-based: if a service logs >= N ERRORs
  within a configurable time window, an incident is opened automatically.
  This logic lives entirely in _check_and_create_incident().

  The LLM (Gemini, via the aiops-genai microservice) is only invoked for
  ROOT CAUSE ANALYSIS *after* an incident already exists.  The AI does NOT
  decide whether an incident should be created.

Threshold configuration (in priority order)
────────────────────────────────────────────
  1. Per-project: projects.error_threshold / projects.error_window_minutes
     (NULL = use global default)
  2. Global env vars: ERROR_THRESHOLD, ERROR_WINDOW_MINUTES
  3. Hard defaults:   5 errors / 5 minutes

Deduplication
─────────────
  1. Log-level (retry storms):
     Each log gets a resolved idempotency_key:
       • Caller-supplied: used as-is
       • Auto-computed:   sha256(project_id:service:level:message:bucket)
     Duplicate key within the window → return existing row, no DB write.

  2. Incident-level (threshold re-crossings):
     Before creating a new incident, check for an open one for the same
     (project_id, service).  If found → bump occurrence_count, no duplicate.
"""

import hashlib
import logging
import math
from datetime import datetime, timedelta, timezone

from core.config import DEDUP_BUCKET_SECONDS, ERROR_THRESHOLD, ERROR_WINDOW_MINUTES
from db.client import supabase
from schemas.logs import LogCreate, LogResponse

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def ingest_log(log: LogCreate) -> LogResponse:
    """
    Ingest a log entry idempotently, then create an incident if the
    per-project (or global) ERROR threshold is crossed and no open
    incident already exists for that (project_id, service).
    """
    # 1️⃣ Resolve project — fetch threshold overrides at the same time
    project_res = (
        supabase.table("projects")
        .select("id, user_id, error_threshold, error_window_minutes")
        .eq("api_key", log.api_key)
        .single()
        .execute()
    )
    if not project_res.data:
        raise ValueError("Invalid API key")

    project       = project_res.data
    project_id: str = project["id"]

    # Resolve effective threshold — per-project wins over global env
    effective_threshold: int = project.get("error_threshold") or ERROR_THRESHOLD
    effective_window: int    = project.get("error_window_minutes") or ERROR_WINDOW_MINUTES

    # 2️⃣ Resolve idempotency key
    idem_key = _resolve_idempotency_key(log, project_id)

    # 3️⃣ Dedup check — is this a duplicate request?
    existing_log = _find_duplicate_log(idem_key, effective_window)
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

    # 5️⃣ Incident detection (ERROR logs only, threshold-based — NOT AI)
    incident_id: str | None = None
    incident_created: bool  = False
    if log.level == "ERROR":
        incident_id, incident_created = _check_and_create_incident(
            project_id, log.service, log.message,
            threshold=effective_threshold,
            window_minutes=effective_window,
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
    Return the caller-supplied key, or auto-compute one from a sha256
    of (project_id, service, level, message, 5-min epoch bucket).

    Two identical log lines within the same bucket produce the same key,
    making retries within that window no-ops.
    """
    if log.idempotency_key:
        return log.idempotency_key

    now_epoch = datetime.now(timezone.utc).timestamp()
    bucket    = math.floor(now_epoch / DEDUP_BUCKET_SECONDS) * DEDUP_BUCKET_SECONDS
    raw       = f"{project_id}:{log.service}:{log.level}:{log.message}:{bucket}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _find_duplicate_log(idem_key: str, window_minutes: int) -> dict | None:
    """
    Look for an existing log row with the same idempotency key written
    within window_minutes.  Returns the row or None.
    Fails open — a DB error here never blocks log ingestion.
    """
    since = (
        datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
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
        return None


def _check_and_create_incident(
    project_id: str,
    service: str,
    message: str,
    *,
    threshold: int,
    window_minutes: int,
) -> tuple[str | None, bool]:
    """
    Threshold-based incident detection (NOT AI-driven).

    Creates an incident when:
      a) >= `threshold` ERRORs from `service` exist in the last `window_minutes`, AND
      b) no OPEN incident already exists for (project_id, service).

    If one already exists → bump occurrence_count, return (existing_id, False).
    Returns (incident_id | None, was_created).
    """
    since = (
        datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
    ).isoformat()

    # Count recent errors for this service
    logs_res = (
        supabase.table("logs")
        .select("id")
        .eq("project_id", project_id)
        .eq("service", service)
        .eq("level", "ERROR")
        .gte("created_at", since)
        .execute()
    )

    error_count = len(logs_res.data)
    if error_count < threshold:
        logger.debug(
            "Error count below threshold — no incident",
            extra={"context": {
                "project_id": project_id,
                "service": service,
                "error_count": error_count,
                "threshold": threshold,
                "window_minutes": window_minutes,
            }},
        )
        return None, False

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
        existing      = existing_res.data[0]
        existing_id: str = existing["id"]
        current_count: int = existing.get("occurrence_count") or 1

        try:
            supabase.table("incidents").update(
                {"occurrence_count": current_count + 1}
            ).eq("id", existing_id).execute()
        except Exception:
            logger.warning(
                "Could not bump occurrence_count (column may not exist yet)",
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
                "occurrence_count": current_count + 1,
            }},
        )
        return existing_id, False

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

        new_id: str = incident_res.data[0]["id"]
        logger.info(
            "New incident created",
            extra={"context": {
                "incident_id": new_id,
                "project_id": project_id,
                "service": service,
                "threshold": threshold,
                "window_minutes": window_minutes,
            }},
        )
        return new_id, True

    except Exception:
        logger.exception(
            "Failed to create incident",
            extra={"context": {"project_id": project_id, "service": service}},
        )
        return None, False
