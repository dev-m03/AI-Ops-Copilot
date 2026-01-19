"""Root cause analysis service using Gemini (google-genai)."""

import json
import os
from datetime import datetime

from google import genai
from app.supabase.client import supabase

# Create Gemini client (NEW SDK)
client = genai.Client(
    api_key=os.getenv("AI_PROVIDER_KEY")
)

MODEL_NAME = "gemini-1.5-flash"

SYSTEM_PROMPT = """
You are a senior Site Reliability Engineer.

Analyze the incident context and return STRICT JSON with this schema:

{
  "root_cause": string,
  "confidence": number between 0 and 1,
  "severity": "low" | "medium" | "high",
  "suggested_fixes": string[],
  "needs_human": boolean
}

Return JSON only.
"""


def analyze_incident(incident_id: str, context: str) -> dict:
    """Analyze incident using Gemini and store results."""

    prompt = f"{SYSTEM_PROMPT}\n\nINCIDENT CONTEXT:\n{context}"

    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
        )

        analysis = json.loads(response.text)

    except Exception:
        # Safe fallback – never crash the pipeline
        analysis = {
            "root_cause": "Unable to determine root cause reliably",
            "confidence": 0.0,
            "severity": "medium",
            "suggested_fixes": ["Review logs manually"],
            "needs_human": True,
        }

    # Persist analysis
    supabase.table("incident_analysis").insert({
        "incident_id": incident_id,
        "root_cause": analysis["root_cause"],
        "confidence": analysis["confidence"],
        "severity": analysis["severity"],
        "suggested_fixes": analysis["suggested_fixes"],
        "needs_human": analysis["needs_human"],
        "created_at": datetime.utcnow().isoformat(),
    }).execute()

    return analysis
