"""
Quick verification tests for aiops-genai/main.py contract fix.
Run from the aiops-genai/ folder:
    pip install fastapi uvicorn httpx pytest python-dotenv google-genai
    pytest test_genai.py -v
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

VALID_PAYLOAD = {"incident_id": "inc-001", "context": "Service crashed after OOM kill"}


# ---------------------------------------------------------------------------
# 1. Correct request shape is accepted (the key fix)
# ---------------------------------------------------------------------------

def test_accepts_context_field_not_text():
    """
    The endpoint must accept 'context', NOT 'text'.
    Before the fix this raised a KeyError and fell through to a 500.
    """
    fake_gemini_response = json.dumps({
        "root_cause": "Memory limit exceeded",
        "confidence": 0.9,
        "severity": "high",
        "suggested_fixes": ["Increase memory limit", "Add OOM alerting"],
        "needs_human": False,
    })

    mock_response = MagicMock()
    mock_response.text = fake_gemini_response

    with patch("main.client.models.generate_content", return_value=mock_response):
        res = client.post("/analyze", json=VALID_PAYLOAD)

    assert res.status_code == 200
    data = res.json()

    # All 5 required fields must be present
    assert "root_cause" in data
    assert "confidence" in data
    assert "severity" in data
    assert "suggested_fixes" in data
    assert "needs_human" in data

    # Values must match the mocked Gemini output
    assert data["root_cause"] == "Memory limit exceeded"
    assert data["confidence"] == 0.9
    assert data["severity"] == "high"
    assert isinstance(data["suggested_fixes"], list)
    assert data["needs_human"] is False


# ---------------------------------------------------------------------------
# 2. Old broken shape ('text' field) is rejected with 422
# ---------------------------------------------------------------------------

def test_rejects_old_text_field():
    """Sending 'text' instead of 'context' should return 422 Unprocessable Entity."""
    res = client.post("/analyze", json={"incident_id": "inc-002", "text": "old field"})
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# 3. Response shape is structured (not the old {"result": "..."} blob)
# ---------------------------------------------------------------------------

def test_response_is_not_raw_result_blob():
    """
    The old broken response returned {"result": "<raw text>"}.
    After the fix it must return the 5-field structured shape.
    """
    fake_response = MagicMock()
    fake_response.text = json.dumps({
        "root_cause": "Disk full",
        "confidence": 0.7,
        "severity": "medium",
        "suggested_fixes": ["Clear logs"],
        "needs_human": True,
    })

    with patch("main.client.models.generate_content", return_value=fake_response):
        res = client.post("/analyze", json=VALID_PAYLOAD)

    assert res.status_code == 200
    data = res.json()
    assert "result" not in data, "OLD broken shape returned — fix not applied"
    assert "root_cause" in data


# ---------------------------------------------------------------------------
# 4. Fallback is returned (not a crash) when Gemini returns bad JSON
# ---------------------------------------------------------------------------

def test_fallback_on_bad_gemini_json():
    """If Gemini returns garbage, the endpoint should return the safe fallback."""
    bad_response = MagicMock()
    bad_response.text = "Sorry, I cannot help with that."

    with patch("main.client.models.generate_content", return_value=bad_response):
        res = client.post("/analyze", json=VALID_PAYLOAD)

    assert res.status_code == 200  # Must NOT be 500
    data = res.json()
    assert data["root_cause"] == "Unable to determine root cause reliably"
    assert data["needs_human"] is True


# ---------------------------------------------------------------------------
# 5. Fallback is returned when Gemini call raises an exception
# ---------------------------------------------------------------------------

def test_fallback_on_gemini_exception():
    """If Gemini throws (timeout, quota exceeded, etc.), return safe fallback."""
    with patch("main.client.models.generate_content", side_effect=Exception("quota exceeded")):
        res = client.post("/analyze", json=VALID_PAYLOAD)

    assert res.status_code == 200  # Must NOT be 500
    data = res.json()
    assert data["confidence"] == 0.0
