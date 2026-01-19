"""
Root Cause Analysis service.

This service:
- Calls the GenAI microservice
- Stores the analysis result in Supabase
"""

from datetime import datetime
import os
import requests

from db.client import supabase

GENAI_URL = os.getenv(
    "GENAI_URL",
    "http://aiops-genai:8001/analyze"
)


def analyze_incident(incident_id: str, context: str) -> dict:
    """
    Analyze an incident using the GenAI service and persist the result.
    """

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
        analysis = response.json()

    except Exception:
        # Absolute safety net – API must NEVER crash
        analysis = {
            "root_cause": "Unable to determine root cause reliably",
            "confidence": 0.0,
            "severity": "medium",
            "suggested_fixes": ["Review logs manually"],
            "needs_human": True,
        }

    # Persist analysis in Supabase
    supabase.table("incident_analysis").insert(
        {
            "incident_id": incident_id,
            "root_cause": analysis["root_cause"],
            "confidence": analysis["confidence"],
            "severity": analysis["severity"],
            "suggested_fixes": analysis["suggested_fixes"],
            "needs_human": analysis["needs_human"],
            "created_at": datetime.utcnow().isoformat(),
        }
    ).execute()

    return analysis
