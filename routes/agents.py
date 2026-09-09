"""Agent management routes."""

from fastapi import APIRouter, Depends, HTTPException
from db.auth import get_current_user
from db.client import supabase
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

    Returns 404 (not 403) when the incident doesn't exist OR doesn't belong
    to the requesting user — this avoids leaking the existence of other
    users' incidents (IDOR prevention).
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

    # 2️⃣ Ownership check — confirm the incident's project belongs to this user
    project_res = (
        supabase
        .table("projects")
        .select("id")
        .eq("id", incident["project_id"])
        .eq("user_id", user_id)        # ownership gate
        .single()
        .execute()
    )

    if not project_res.data:
        # Return 404 intentionally — 403 would leak that the incident exists
        raise HTTPException(status_code=404, detail="Incident not found")

    # 3️⃣ Build context
    context = (
        f"Service: {incident['service']}\n"
        f"Summary: {incident['summary']}\n"
        f"Severity: {incident['severity']}"
    )

    # 4️⃣ Run RCA analysis
    analysis = analyze_incident(incident_id, context)

    # 5️⃣ Run agent decision engine
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
