"""
Tests for IDOR prevention in POST /agents/analyze/{incident_id}.

Confirms:
- User A can analyze their own incident (200)
- User A cannot analyze User B's incident (404, not 403)
- A completely non-existent incident returns 404
"""

import os
os.environ["SUPABASE_URL"] = "https://fake.supabase.co"

from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from fastapi import FastAPI

from db.auth import get_current_user
import routes.agents as agents_module
from routes.agents import router

# ── minimal app ───────────────────────────────────────────────────────────────
app = FastAPI()
app.include_router(router)
client = TestClient(app, raise_server_exceptions=False)

# ── shared fixtures ───────────────────────────────────────────────────────────
USER_A = "user-A-uuid"
USER_B = "user-B-uuid"

INCIDENT = {
    "id": "incident-001",
    "project_id": "project-A",
    "service": "auth-service",
    "summary": "Connection refused on port 5432",
    "severity": "high",
}

PROJECT_A = {"id": "project-A"}


def _make_supabase_mock(incident_data, project_data):
    """
    Build a Supabase mock that returns different data for the two sequential
    .table() calls inside analyze_and_decide:
      call 1 → incidents table  → incident_data
      call 2 → projects table   → project_data
    """
    def _chain(data):
        m = MagicMock()
        m.select.return_value = m
        m.eq.return_value = m
        m.single.return_value = m
        m.execute.return_value = MagicMock(data=data)
        return m

    root = MagicMock()
    root.table.side_effect = [_chain(incident_data), _chain(project_data)]
    return root


# ── tests ─────────────────────────────────────────────────────────────────────

def test_owner_can_analyze_own_incident():
    """User A analyzing their own incident → 200."""
    mock_analysis = {
        "root_cause": "DB down",
        "confidence": 0.9,
        "severity": "high",
        "suggested_fixes": ["Restart DB"],
        "needs_human": False,
    }
    mock_decision = {"action": "restart", "automated": True}

    # Override auth dependency so no real JWT verification happens
    app.dependency_overrides[get_current_user] = lambda: USER_A

    with (
        patch.object(agents_module, "supabase", _make_supabase_mock(INCIDENT, PROJECT_A)),
        patch("routes.agents.analyze_incident", return_value=mock_analysis),
        patch("routes.agents.run_agent", return_value=mock_decision),
    ):
        res = client.post(
            f"/agents/analyze/{INCIDENT['id']}",
            headers={"Authorization": "Bearer fake"},
        )

    app.dependency_overrides.clear()

    assert res.status_code == 200
    data = res.json()
    assert data["incident_id"] == INCIDENT["id"]
    assert data["analysis"]["root_cause"] == "DB down"


def test_non_owner_gets_404_not_403():
    """
    User B tries to analyze User A's incident.
    Ownership check (project.user_id != USER_B) fails → must be 404,
    never 403 (which would leak that the incident exists).
    """
    app.dependency_overrides[get_current_user] = lambda: USER_B

    # Incident exists but project lookup returns None (wrong user_id)
    with patch.object(agents_module, "supabase", _make_supabase_mock(INCIDENT, None)):
        res = client.post(
            f"/agents/analyze/{INCIDENT['id']}",
            headers={"Authorization": "Bearer fake"},
        )

    app.dependency_overrides.clear()

    assert res.status_code == 404
    assert res.status_code != 403   # 403 leaks existence — must not happen


def test_nonexistent_incident_returns_404():
    """Incident doesn't exist at all → 404."""
    app.dependency_overrides[get_current_user] = lambda: USER_A

    with patch.object(agents_module, "supabase", _make_supabase_mock(None, None)):
        res = client.post(
            "/agents/analyze/does-not-exist",
            headers={"Authorization": "Bearer fake"},
        )

    app.dependency_overrides.clear()

    assert res.status_code == 404
