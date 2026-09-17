"""
Root Cause Analysis service.

This service:
- Calls the GenAI microservice with { incident_id, context }
- Retries up to 3 times with exponential backoff on 429 / 503 (Render cold-start)
- Validates the response against a Pydantic model before use
- Stores the validated analysis result in Supabase
- Falls back safely if the GenAI service is unreachable or returns bad data

Why retries?
────────────
Render's free tier spins services down after inactivity. The first request to a
sleeping instance can get a 429 (Too Many Requests) or 503 (Service Unavailable)
while the container is waking up (~15-30 s). Retrying with backoff absorbs this
cold-start window instead of surfacing a confusing fallback to the user.
"""

import logging
import os
import time
from datetime import UTC, datetime
from typing import Literal

import requests
from pydantic import BaseModel, ValidationError

from db.client import supabase

logger = logging.getLogger(__name__)

GENAI_URL = os.getenv(
    "GENAI_URL",
    "http://aiops-genai:8001/analyze"
)

# ── Retry configuration ────────────────────────────────────────────────────────
# These are the HTTP status codes that indicate a transient failure worth retrying.
# 429 = rate-limited / cold-start on Render free tier
# 503 = service temporarily unavailable (also common on cold start)
_RETRYABLE_STATUSES = {429, 503, 502, 504}

# How many times to attempt the call (1 attempt + 2 retries = 3 total)
_MAX_ATTEMPTS = 3

# Initial backoff in seconds. Each retry doubles this (exponential backoff):
#   Attempt 1 → immediate
#   Attempt 2 → wait 2 s
#   Attempt 3 → wait 4 s
_BACKOFF_BASE = 2


# ---------------------------------------------------------------------------
# Response model — must stay in sync with aiops-genai/main.py's AnalyzeResponse
# ---------------------------------------------------------------------------

class RCAAnalysisResult(BaseModel):
    """Expected shape of the GenAI microservice response."""
    root_cause: str
    confidence: float
    severity: Literal["low", "medium", "high"]
    suggested_fixes: list[str]
    needs_human: bool


# ---------------------------------------------------------------------------
# Safe fallback value
# ---------------------------------------------------------------------------

_FALLBACK = RCAAnalysisResult(
    root_cause="Unable to determine root cause reliably",
    confidence=0.0,
    severity="medium",
    suggested_fixes=["Review logs manually"],
    needs_human=True,
)


def _call_genai_with_retry(incident_id: str, context: str) -> RCAAnalysisResult:
    """
    POST to the GenAI microservice with retry + exponential backoff.

    Retries on 429 / 503 / 502 / 504 (transient / cold-start errors).
    Raises immediately on non-retryable HTTP errors (4xx other than 429).
    Returns _FALLBACK if all attempts are exhausted or a non-HTTP error occurs.
    """
    last_exc: Exception | None = None

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            response = requests.post(
                GENAI_URL,
                json={"incident_id": incident_id, "context": context},
                timeout=35,
            )

            # Check if this is a retryable status code
            if response.status_code in _RETRYABLE_STATUSES:
                wait = _BACKOFF_BASE ** (attempt - 1)   # 1s, 2s, 4s
                logger.warning(
                    "GenAI service returned %s (attempt %d/%d) — retrying in %ds",
                    response.status_code, attempt, _MAX_ATTEMPTS, wait,
                    extra={"context": {"incident_id": incident_id, "genai_url": GENAI_URL}},
                )
                if attempt < _MAX_ATTEMPTS:
                    time.sleep(wait)
                continue   # move to next attempt

            # Non-retryable HTTP error (e.g. 400, 401, 422)
            response.raise_for_status()

            # ✅ Success — validate and return
            return RCAAnalysisResult(**response.json())

        except ValidationError:
            logger.exception(
                "GenAI response failed schema validation — using fallback",
                extra={"context": {"incident_id": incident_id, "genai_url": GENAI_URL}},
            )
            return _FALLBACK   # schema mismatch is not retryable

        except requests.exceptions.HTTPError:
            # Non-retryable HTTP error (raised by raise_for_status above)
            raise

        except Exception as exc:
            last_exc = exc
            wait = _BACKOFF_BASE ** (attempt - 1)
            logger.warning(
                "GenAI call failed (attempt %d/%d): %s — retrying in %ds",
                attempt, _MAX_ATTEMPTS, exc, wait,
                extra={"context": {"incident_id": incident_id, "genai_url": GENAI_URL}},
            )
            if attempt < _MAX_ATTEMPTS:
                time.sleep(wait)

    # All attempts exhausted
    logger.error(
        "GenAI service unreachable after %d attempts — using fallback",
        _MAX_ATTEMPTS,
        extra={"context": {"incident_id": incident_id, "last_error": str(last_exc)}},
    )
    return _FALLBACK


def analyze_incident(incident_id: str, context: str) -> dict:
    """
    Analyze an incident using the GenAI service and persist the result.

    Returns a dict with keys: root_cause, confidence, severity,
    suggested_fixes, needs_human.
    """
    analysis: RCAAnalysisResult = _FALLBACK

    try:
        analysis = _call_genai_with_retry(incident_id, context)
    except Exception:
        logger.exception(
            "GenAI HTTP call failed — using fallback",
            extra={"context": {"incident_id": incident_id, "genai_url": GENAI_URL}},
        )

    # Persist analysis in Supabase
    try:
        supabase.table("incident_analysis").insert(
            {
                "incident_id": incident_id,
                "root_cause": analysis.root_cause,
                "confidence": analysis.confidence,
                "severity": analysis.severity,
                "suggested_fixes": analysis.suggested_fixes,
                "needs_human": analysis.needs_human,
                "created_at": datetime.now(UTC).isoformat(),
            }
        ).execute()
    except Exception:
        logger.exception(
            "Failed to persist RCA analysis to Supabase",
            extra={"context": {"incident_id": incident_id}},
        )

    return analysis.model_dump()
