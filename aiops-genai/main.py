"""
AI Ops GenAI Microservice.

Accepts an incident_id and context string, calls Gemini with a structured
JSON prompt, and returns a typed RCA analysis result.

Request shape  : { "incident_id": str, "context": str }
Response shape : { "root_cause": str, "confidence": float,
                   "severity": "low"|"medium"|"high",
                   "suggested_fixes": list[str], "needs_human": bool }
"""

import json
import os
from typing import Literal

import google.generativeai as genai
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel, ValidationError

load_dotenv()

genai.configure(api_key=os.getenv("AI_PROVIDER_KEY"))

app = FastAPI(title="AI Ops GenAI Service")

# ---------------------------------------------------------------------------
# Shared contract models
# ---------------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    """What the main API sends us."""
    incident_id: str
    context: str


class AnalyzeResponse(BaseModel):
    """Structured RCA result — must match what rca_service.py expects to persist."""
    root_cause: str
    confidence: float          # 0.0 – 1.0
    severity: Literal["low", "medium", "high"]
    suggested_fixes: list[str]
    needs_human: bool


# ---------------------------------------------------------------------------
# Safe fallback (returned when Gemini is unavailable or returns bad JSON)
# ---------------------------------------------------------------------------

def _fallback(incident_id: str) -> AnalyzeResponse:
    return AnalyzeResponse(
        root_cause="Unable to determine root cause reliably",
        confidence=0.0,
        severity="medium",
        suggested_fixes=["Review logs manually"],
        needs_human=True,
    )


# ---------------------------------------------------------------------------
# Prompt template — asks Gemini for strict JSON matching AnalyzeResponse
# ---------------------------------------------------------------------------

PROMPT_TEMPLATE = """
You are an AI Ops assistant performing root cause analysis.

Analyze the following incident context and respond with **only** a JSON object
— no markdown fences, no explanation — in this exact shape:

{{
  "root_cause": "<concise one-sentence root cause>",
  "confidence": <float 0.0-1.0>,
  "severity": "<low|medium|high>",
  "suggested_fixes": ["<fix 1>", "<fix 2>"],
  "needs_human": <true|false>
}}

Incident context:
{context}
""".strip()


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    """
    Analyze an incident and return a structured RCA result.
    Falls back safely if Gemini is unavailable or returns unexpected output.
    """
    prompt = PROMPT_TEMPLATE.format(context=request.context)

    print(f"[genai] calling Gemini for incident: {request.incident_id}", flush=True)

    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(prompt)

        raw_text = response.text.strip()
        print(f"[genai] Gemini raw response: {raw_text[:300]}", flush=True)

        # Strip accidental markdown code fences if Gemini adds them
        if raw_text.startswith("```"):
            lines = raw_text.splitlines()
            raw_text = "\n".join(
                line for line in lines
                if not line.startswith("```")
            ).strip()

        parsed = json.loads(raw_text)
        return AnalyzeResponse(**parsed)

    except (json.JSONDecodeError, ValidationError, KeyError) as e:
        print(f"[genai] Parse error: {type(e).__name__}: {e}", flush=True)
        return _fallback(request.incident_id)

    except Exception as e:
        print(f"[genai] Gemini call failed: {type(e).__name__}: {e}", flush=True)
        return _fallback(request.incident_id)
