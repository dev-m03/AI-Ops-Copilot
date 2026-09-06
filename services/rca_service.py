"""
Root Cause Analysis service.

This service:
- Calls the GenAI microservice with { incident_id, context }
- Validates the response against a Pydantic model before use
- Stores the validated analysis result in Supabase
- Falls back safely if the GenAI service is unreachable or returns bad data
"""

import os
from datetime import datetime
from typing import Literal

import requests
from pydantic import BaseModel, ValidationError

from db.client import supabase

GENAI_URL = os.getenv(
    "GENAI_URL",
    "http://aiops-genai:8001/analyze"
)


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


def analyze_incident(incident_id: str, context: str) -> dict:
    """
    Analyze an incident using the GenAI service and persist the result.

    Returns a dict with keys: root_cause, confidence, severity,
    suggested_fixes, needs_human.
    """

    analysis: RCAAnalysisResult = _FALLBACK

    try:
        response = requests.post(
            GENAI_URL,
            json={
                "incident_id": incident_id,
                "context": context,
            },
            timeout=30,
        )
        response.raise_for_status()

        # Validate the response shape before trusting any fields
        analysis = RCAAnalysisResult(**response.json())

    except ValidationError:
        # GenAI service returned an unexpected shape — use fallback
        # (the fallback is already assigned above; nothing extra needed here)
        pass

    except Exception:
        # Network error, timeout, non-2xx status, etc. — use fallback
        pass

    # Persist analysis in Supabase
    supabase.table("incident_analysis").insert(
        {
            "incident_id": incident_id,
            "root_cause": analysis.root_cause,
            "confidence": analysis.confidence,
            "severity": analysis.severity,
            "suggested_fixes": analysis.suggested_fixes,
            "needs_human": analysis.needs_human,
            "created_at": datetime.utcnow().isoformat(),
        }
    ).execute()

    return analysis.model_dump()
