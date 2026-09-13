"""
Table-driven tests for agents/policies.py (decide_action) and
agents/decision_engine.py (run_agent).

decide_action logic (from policies.py)
---------------------------------------
  confidence < 0.6          → "notify"
  confidence >= 0.6 AND
    severity == "high"       → "alert"
  confidence >= 0.6 AND
    severity != "high"       → "suggest"

run_agent wraps decide_action — we verify it:
  • returns the expected action
  • attempts execution for "alert" / "notify" actions
  • sets executed=True on success, records message on failure
"""
import pytest
from unittest.mock import patch, MagicMock

from agents.policies import decide_action
from agents.decision_engine import run_agent


# ── Table-driven tests for decide_action ─────────────────────────────────────

@pytest.mark.parametrize("confidence,severity,expected_action", [
    # Low confidence → always "notify" regardless of severity
    (0.0,  "high",   "notify"),
    (0.3,  "high",   "notify"),
    (0.59, "medium", "notify"),
    (0.59, "low",    "notify"),
    (0.59, "high",   "notify"),

    # Confidence exactly at boundary (0.6) — high severity → "alert"
    (0.6,  "high",   "alert"),
    (0.75, "high",   "alert"),
    (1.0,  "high",   "alert"),

    # Confidence >= 0.6 but severity not "high" → "suggest"
    (0.6,  "medium", "suggest"),
    (0.6,  "low",    "suggest"),
    (0.8,  "medium", "suggest"),
    (0.8,  "low",    "suggest"),
    (1.0,  "medium", "suggest"),
])
def test_decide_action_table(confidence, severity, expected_action):
    analysis = {"confidence": confidence, "severity": severity}
    assert decide_action(analysis) == expected_action


# ── run_agent tests ───────────────────────────────────────────────────────────

_BASE_INCIDENT = {
    "id": "inc-999",
    "service": "payment-service",
    "summary": "DB down",
    "severity": "high",
}


def test_run_agent_returns_expected_keys():
    """run_agent always returns a dict with all required keys."""
    analysis = {"confidence": 0.9, "severity": "high"}
    result = run_agent(_BASE_INCIDENT, analysis)

    assert "incident_id" in result
    assert "action" in result
    assert "executed" in result
    assert "message" in result
    assert result["incident_id"] == "inc-999"


def test_run_agent_alert_action_executed():
    """High-confidence + high-severity → action='alert', executed=True on success."""
    analysis = {"confidence": 0.9, "severity": "high"}

    with patch("agents.decision_engine.execute_action", return_value=True) as mock_exec:
        result = run_agent(_BASE_INCIDENT, analysis)

    assert result["action"] == "alert"
    assert result["executed"] is True
    assert result["message"] is not None
    mock_exec.assert_called_once_with("alert", _BASE_INCIDENT, analysis)


def test_run_agent_notify_action_executed():
    """Low-confidence → action='notify', execute_action is called."""
    analysis = {"confidence": 0.4, "severity": "high"}

    with patch("agents.decision_engine.execute_action", return_value=True):
        result = run_agent(_BASE_INCIDENT, analysis)

    assert result["action"] == "notify"
    assert result["executed"] is True


def test_run_agent_suggest_action_not_executed():
    """
    'suggest' is not in the ["alert", "notify"] list → execute_action is
    NOT called and executed stays False.
    """
    analysis = {"confidence": 0.8, "severity": "medium"}

    with patch("agents.decision_engine.execute_action") as mock_exec:
        result = run_agent(_BASE_INCIDENT, analysis)

    assert result["action"] == "suggest"
    assert result["executed"] is False
    mock_exec.assert_not_called()


def test_run_agent_execution_failure_sets_message():
    """If execute_action raises, executed stays False and message records the error."""
    analysis = {"confidence": 0.9, "severity": "high"}

    with patch(
        "agents.decision_engine.execute_action",
        side_effect=RuntimeError("downstream unavailable"),
    ):
        result = run_agent(_BASE_INCIDENT, analysis)

    assert result["executed"] is False
    assert "downstream unavailable" in result["message"]
