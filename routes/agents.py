"""Agent management routes."""

from fastapi import APIRouter, Depends, HTTPException
from supabase.auth import get_current_user
from supabase.client import supabase
from services.rca_service import analyze_incident
from agents.decision_engine import run_agent

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("/analyze/{incident_id}")
def analyze_and_decide(
    incident_id: str,
    user_id: str = Depends(get_current_user),
):
    """
    Run RCA analysis and agent decision on an incident.
    MVP-safe version (no redundant ownership check).
    """

    # 1️⃣ Fetch incident
    incident_res = (
        supabase
        .table("incidents")
        .select("*")
        .eq("id", incident_id)
        .single()
        .execute()
    )

    if not incident_res.data:
        raise HTTPException(status_code=404, detail="Incident not found")

    incident = incident_res.data

    # 2️⃣ Build context
    context = (
        f"Service: {incident['service']}\n"
        f"Summary: {incident['summary']}\n"
        f"Severity: {incident['severity']}"
    )

    # 3️⃣ Run RCA analysis
    analysis = analyze_incident(incident_id, context)

    # 4️⃣ Run agent decision engine
    decision = run_agent(
        {
            "id": incident["id"],
            "service": incident["service"],
            "summary": incident["summary"],
            "severity": incident["severity"],
        },
        analysis,
    )

    return {
        "incident_id": incident_id,
        "analysis": analysis,
        "decision": decision,
    }
