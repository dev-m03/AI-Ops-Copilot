"""
IDOR-prevention tests for POST /agents/analyze/{incident_id}  (routes/agents.py).

Confirms that:
- A valid owner gets a 200 with analysis + decision fields present.
- User A cannot read User B's incident  → 404 (not 403 — 403 leaks existence).
- A completely non-existent incident_id → 404.
"""
# ── Env setup ─────────────────────────────────────────────────────────────────
import os
os.environ.setdefault("SUPABASE_URL", "https://fake.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "fake-key")

from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from db.auth import get_current_user
import routes.agents as agents_module
from routes.agents import router

# ── Minimal test app ──────────────────────────────────────────────────────────
_app = FastAPI()
_app.include_router(router)
_client = TestClient(_app, raise_server_exceptions=False)

# ── Shared fixtures ───────────────────────────────────────────────────────────
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

MOCK_ANALYSIS = {
    "root_cause": "DB connection pool exhausted",
    "confidence": 0.9,
    "severity": "high",
    "suggested_fixes": ["Increase pool size", "Add connection retry"],
    "needs_human": False,
}

MOCK_DECISION = {
    "incident_id": INCIDENT["id"],
    "action": "alert",
    "executed": True,
    "message": "Action 'alert' executed",
}


# ── Supabase mock builder ─────────────────────────────────────────────────────

def _make_supabase_mock(incident_data, project_data):
    """
    Build a Supabase client mock satisfying the two sequential .table() calls
    that analyze_and_decide() makes:
      call 1 → incidents table
      call 2 → projects table
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


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_owner_gets_200_with_analysis_and_decision():
    """Valid owner requesting their own incident → 200 with all expected fields."""
    _app.dependency_overrides[get_current_user] = lambda: USER_A
    try:
        with (
            patch.object(agents_module, "supabase", _make_supabase_mock(INCIDENT, PROJECT_A)),
            patch("routes.agents.analyze_incident", return_value=MOCK_ANALYSIS),
            patch("routes.agents.run_agent", return_value=MOCK_DECISION),
        ):
            res = _client.post(
                f"/agents/analyze/{INCIDENT['id']}",
                headers={"Authorization": "Bearer fake"},
            )
    finally:
        _app.dependency_overrides.clear()

    assert res.status_code == 200
    data = res.json()
    assert data["incident_id"] == INCIDENT["id"]
    # analysis fields
    assert data["analysis"]["root_cause"] == MOCK_ANALYSIS["root_cause"]
    assert data["analysis"]["confidence"] == MOCK_ANALYSIS["confidence"]
    assert data["analysis"]["severity"] == MOCK_ANALYSIS["severity"]
    # decision field present
    assert "decision" in data
    assert data["decision"]["action"] == "alert"


def test_non_owner_gets_404_not_403():
    """
    User B tries to access User A's incident.
    The project ownership check fails (project not found for USER_B).
    Must return 404 — never 403, which would reveal the incident exists.
    """
    _app.dependency_overrides[get_current_user] = lambda: USER_B
    try:
        # Incident is found, but the project-level ownership check returns None
        with patch.object(
            agents_module, "supabase", _make_supabase_mock(INCIDENT, None)
        ):
            res = _client.post(
                f"/agents/analyze/{INCIDENT['id']}",
                headers={"Authorization": "Bearer fake"},
            )
    finally:
        _app.dependency_overrides.clear()

    assert res.status_code == 404
    assert res.status_code != 403, "403 leaks incident existence — must never be returned"


def test_nonexistent_incident_returns_404():
    """Incident_id that doesn't exist at all → 404."""
    _app.dependency_overrides[get_current_user] = lambda: USER_A
    try:
        with patch.object(
            agents_module, "supabase", _make_supabase_mock(None, None)
        ):
            res = _client.post(
                "/agents/analyze/does-not-exist",
                headers={"Authorization": "Bearer fake"},
            )
    finally:
        _app.dependency_overrides.clear()

    assert res.status_code == 404
