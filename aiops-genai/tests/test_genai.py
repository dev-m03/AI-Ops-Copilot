"""
Tests for aiops-genai/main.py  (the Gemini-backed microservice).

IMPORTANT — how to run these tests:
    # From the aiops-genai/ directory (recommended):
    cd aiops-genai
    pytest

    # From the repo root (also works):
    pytest aiops-genai/tests/ --rootdir=aiops-genai/

Covers
------
1. Valid strict-JSON response → parses into AnalyzeResponse correctly.
2. Response wrapped in markdown code fences → fence-stripping → same result.
3. Malformed / non-JSON response → _fallback() returned (200, needs_human=True).
4. JSON with wrong schema → ValidationError → _fallback().
5. 503 on the first model → fallthrough to the next model.
6. 429 on the first model → fallthrough to the next model.
7. Non-retryable error → immediate fallback (only 1 model tried).
8. All models exhausted with retryable errors → fallback after 3 attempts.
"""
import json
import os
import sys

# ── Ensure aiops-genai/ is first on sys.path so `import main` resolves to
# aiops-genai/main.py, not the repo-root main.py ────────────────────────────
_GENAI_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _GENAI_ROOT not in sys.path:
    sys.path.insert(0, _GENAI_ROOT)
elif sys.path[0] != _GENAI_ROOT:
    # Repo root was prepended by pytest's pythonpath setting; move genai to front
    sys.path.remove(_GENAI_ROOT)
    sys.path.insert(0, _GENAI_ROOT)

import importlib
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

os.environ.setdefault("AI_PROVIDER_KEY", "test-key")

# Import the genai main module with Client patched to avoid needing an API key
with patch("google.genai.Client"):
    import main as genai_main
    importlib.reload(genai_main)  # guarantee it's aiops-genai/main, not repo-root main

_test_client = TestClient(genai_main.app)

VALID_PAYLOAD = {"incident_id": "inc-001", "context": "Service crashed after OOM kill"}

VALID_GEMINI_JSON = {
    "root_cause": "Memory limit exceeded",
    "confidence": 0.9,
    "severity": "high",
    "suggested_fixes": ["Increase memory limit", "Add OOM alerting"],
    "needs_human": False,
}


def _mock_response(text: str) -> MagicMock:
    m = MagicMock()
    m.text = text
    return m


# ── 1. Valid strict-JSON response ─────────────────────────────────────────────

def test_valid_strict_json_response_parsed_correctly():
    """Clean JSON from Gemini → full AnalyzeResponse, all fields correct."""
    with patch.object(
        genai_main.client.models, "generate_content",
        return_value=_mock_response(json.dumps(VALID_GEMINI_JSON))
    ):
        res = _test_client.post("/analyze", json=VALID_PAYLOAD)

    assert res.status_code == 200
    data = res.json()
    assert data["root_cause"] == VALID_GEMINI_JSON["root_cause"]
    assert data["confidence"] == VALID_GEMINI_JSON["confidence"]
    assert data["severity"] == VALID_GEMINI_JSON["severity"]
    assert data["suggested_fixes"] == VALID_GEMINI_JSON["suggested_fixes"]
    assert data["needs_human"] is False


# ── 2. Markdown code-fence stripping ─────────────────────────────────────────

def test_markdown_fenced_json_parsed_correctly():
    """Response wrapped in ```json ... ``` fences → same result as clean JSON."""
    fenced = f"```json\n{json.dumps(VALID_GEMINI_JSON)}\n```"

    with patch.object(
        genai_main.client.models, "generate_content",
        return_value=_mock_response(fenced)
    ):
        res = _test_client.post("/analyze", json=VALID_PAYLOAD)

    assert res.status_code == 200
    data = res.json()
    assert data["root_cause"] == VALID_GEMINI_JSON["root_cause"]
    assert data["severity"] == VALID_GEMINI_JSON["severity"]


def test_plain_fenced_json_parsed_correctly():
    """Response wrapped in plain ``` fences (no language tag) is also stripped."""
    fenced = f"```\n{json.dumps(VALID_GEMINI_JSON)}\n```"

    with patch.object(
        genai_main.client.models, "generate_content",
        return_value=_mock_response(fenced)
    ):
        res = _test_client.post("/analyze", json=VALID_PAYLOAD)

    assert res.status_code == 200
    assert res.json()["root_cause"] == VALID_GEMINI_JSON["root_cause"]


# ── 3. Malformed JSON → _fallback ─────────────────────────────────────────────

def test_malformed_json_triggers_fallback():
    """Non-JSON text from Gemini → safe fallback response (200, needs_human=True)."""
    with patch.object(
        genai_main.client.models, "generate_content",
        return_value=_mock_response("Sorry, I cannot help.")
    ):
        res = _test_client.post("/analyze", json=VALID_PAYLOAD)

    assert res.status_code == 200
    data = res.json()
    assert data["root_cause"] == "Unable to determine root cause reliably"
    assert data["needs_human"] is True
    assert data["confidence"] == 0.0


# ── 4. Wrong schema → ValidationError → fallback ─────────────────────────────

def test_valid_json_with_wrong_schema_triggers_fallback():
    """JSON that doesn't match AnalyzeResponse schema → ValidationError → fallback."""
    bad_schema = {"wrong_key": "oops", "confidence": "not-a-float"}

    with patch.object(
        genai_main.client.models, "generate_content",
        return_value=_mock_response(json.dumps(bad_schema))
    ):
        res = _test_client.post("/analyze", json=VALID_PAYLOAD)

    assert res.status_code == 200
    assert res.json()["needs_human"] is True


# ── 5. 503 on first model → fallthrough ──────────────────────────────────────

def test_503_on_first_model_falls_through_to_next():
    """When model #0 raises a 503, the service retries model #1."""
    def _side_effect(model, contents):
        if "lite" in model:   # first model in models_to_try
            raise Exception("503 Service Unavailable")
        return _mock_response(json.dumps(VALID_GEMINI_JSON))

    with patch.object(genai_main.client.models, "generate_content", side_effect=_side_effect):
        res = _test_client.post("/analyze", json=VALID_PAYLOAD)

    assert res.status_code == 200
    assert res.json()["root_cause"] == VALID_GEMINI_JSON["root_cause"]


# ── 6. 429 on first model → fallthrough ──────────────────────────────────────

def test_429_on_first_model_falls_through_to_next():
    """429 (rate-limit) on model #0 → tries model #1."""
    call_count = {"n": 0}

    def _side_effect(model, contents):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise Exception("429 Too Many Requests")
        return _mock_response(json.dumps(VALID_GEMINI_JSON))

    with patch.object(genai_main.client.models, "generate_content", side_effect=_side_effect):
        res = _test_client.post("/analyze", json=VALID_PAYLOAD)

    assert res.status_code == 200
    assert call_count["n"] == 2  # exactly 2 attempts


# ── 7. Non-retryable error → immediate fallback ───────────────────────────────

def test_non_retryable_error_returns_fallback_without_further_tries():
    """
    A generic / non-retryable exception (no 503/429 in message) must return the
    fallback immediately — no further models should be tried.
    """
    call_count = {"n": 0}

    def _side_effect(model, contents):
        call_count["n"] += 1
        raise ValueError("Unexpected internal error")  # non-retryable

    with patch.object(genai_main.client.models, "generate_content", side_effect=_side_effect):
        res = _test_client.post("/analyze", json=VALID_PAYLOAD)

    assert res.status_code == 200
    assert res.json()["needs_human"] is True
    assert call_count["n"] == 1   # only 1 model tried


# ── 8. All models exhausted → fallback ───────────────────────────────────────

def test_all_models_exhausted_returns_fallback():
    """All 3 models raise retryable (503) errors → fallback returned."""
    call_count = {"n": 0}

    def _side_effect(model, contents):
        call_count["n"] += 1
        raise Exception("503 UNAVAILABLE")

    with patch.object(genai_main.client.models, "generate_content", side_effect=_side_effect):
        res = _test_client.post("/analyze", json=VALID_PAYLOAD)

    assert res.status_code == 200
    assert res.json()["needs_human"] is True
    assert call_count["n"] == 3   # all 3 models tried
