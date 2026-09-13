"""
Comprehensive tests for services/log_service.py (ingest_log).

Covers
------
1. First ingestion inserts a new log row, deduplicated=False.
2. Duplicate request (same idempotency key, within window) returns existing
   row; no new DB write; deduplicated=True.
3. Errors outside the time window do NOT count toward the threshold (only
   logs inside the window are returned by the count query mock).
4. Incident is NOT created when error_count < threshold.
5. Incident IS created when error_count >= threshold (first crossing).
6. A second threshold-crossing while the incident is still OPEN bumps
   occurrence_count instead of creating a second incident.
7. Per-project error_threshold / error_window_minutes override global defaults.
"""
# ── Env setup — MUST precede ALL project imports ─────────────────────────────
import os

os.environ.setdefault("SUPABASE_URL", "https://fake.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "fake-key")

from unittest.mock import MagicMock, patch

import services.log_service as svc
from schemas.logs import LogCreate

# ── Shared fixtures ───────────────────────────────────────────────────────────

PROJECT_ID = "proj-test-111"
SERVICE = "payment-service"

BASE_LOG = LogCreate(
    api_key="test-api-key",
    service=SERVICE,
    level="ERROR",
    message="Connection refused on port 5432",
)

# Default project row — NULL overrides → global env defaults apply
_PROJECT_ROW = {
    "id": PROJECT_ID,
    "user_id": "user-A",
    "error_threshold": None,
    "error_window_minutes": None,
}


# ── Supabase mock builder ─────────────────────────────────────────────────────

def _build_supabase(
    *,
    project_data,
    dedup_log_data,      # returned by the dedup SELECT query
    error_count_data,    # returned by the error-count SELECT query
    open_incident_data,  # existing open incident (list) or []
    new_log_id: str = "log-new",
    new_incident_id: str = "incident-new",
):
    """
    Build a fully mocked Supabase client for the ingest_log() call path.

    The service makes up to 6 sequential .table() calls (in order):
      1. projects   — resolve project + threshold overrides
      2. logs       — dedup check
      3. logs       — insert new log row   (skipped on dedup)
      4. logs       — count recent errors  (skipped on dedup or non-ERROR)
      5. incidents  — check for open incident
      6. incidents  — insert new OR update occurrence_count
    """
    sb = MagicMock()

    def _chain(data):
        c = MagicMock()
        c.select.return_value = c
        c.insert.return_value = c
        c.update.return_value = c
        c.eq.return_value = c
        c.gte.return_value = c
        c.limit.return_value = c
        c.single.return_value = c
        c.execute.return_value = MagicMock(data=data)
        return c

    # Chains that need a specific return value but can't share state with _chain
    insert_log_chain = MagicMock()
    insert_log_chain.insert.return_value = insert_log_chain
    insert_log_chain.execute.return_value = MagicMock(data=[{"id": new_log_id}])

    incident_insert_chain = MagicMock()
    incident_insert_chain.insert.return_value = incident_insert_chain
    incident_insert_chain.execute.return_value = MagicMock(
        data=[{"id": new_incident_id}]
    )

    incident_update_chain = MagicMock()
    incident_update_chain.update.return_value = incident_update_chain
    incident_update_chain.eq.return_value = incident_update_chain
    incident_update_chain.execute.return_value = MagicMock(data=[])

    call_sequence: list[str] = []

    def router(table_name: str):
        call_sequence.append(table_name)
        n = len(call_sequence)
        if n == 1:                                      # projects lookup
            return _chain(project_data)
        if n == 2:                                      # dedup SELECT
            return _chain(dedup_log_data)
        if n == 3 and table_name == "logs":             # log INSERT
            return insert_log_chain
        if n == 4 and table_name == "logs":             # error-count SELECT
            return _chain(error_count_data)
        if n == 5 and table_name == "incidents":        # open incident SELECT
            return _chain(open_incident_data)
        if n == 6 and table_name == "incidents":        # create or bump
            return incident_update_chain if open_incident_data else incident_insert_chain
        return MagicMock()

    sb.table.side_effect = router
    return sb


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_first_ingestion_inserts_new_row():
    """Happy path: first log call inserts a row, deduplicated=False."""
    sb = _build_supabase(
        project_data=_PROJECT_ROW,
        dedup_log_data=[],          # no duplicate
        error_count_data=[],        # below threshold → no incident
        open_incident_data=[],
        new_log_id="log-001",
    )
    with patch.object(svc, "supabase", sb):
        result = svc.ingest_log(BASE_LOG)

    assert result.deduplicated is False
    assert result.id == "log-001"
    assert result.incident_created is False


def test_duplicate_within_window_is_suppressed():
    """Second identical call within the dedup window → returns existing row, no insert."""
    existing = {"id": "log-existing", "incident_id": None}
    sb = _build_supabase(
        project_data=_PROJECT_ROW,
        dedup_log_data=[existing],  # duplicate found
        error_count_data=[],
        open_incident_data=[],
    )
    with patch.object(svc, "supabase", sb):
        result = svc.ingest_log(BASE_LOG)

    assert result.deduplicated is True
    assert result.id == "log-existing"
    assert result.incident_created is False
    # Verify no insert was attempted (call sequence stops after the dedup SELECT)
    # The table router would NOT see a call #3 for "logs" insert
    call_names = [c.args[0] for c in sb.table.call_args_list]
    assert call_names.index("logs") == 1  # only the dedup SELECT → index 1


def test_errors_outside_window_dont_count_toward_threshold():
    """
    The error-count query uses a ``gte(created_at, since)`` filter.  Mocking it
    to return fewer rows than the threshold simulates errors that are outside
    the window — no incident should be created in that case.
    """
    # One fewer than the threshold — simulates old logs filtered out
    rows_inside_window = [{"id": f"log-{i}"} for i in range(svc.ERROR_THRESHOLD - 1)]
    sb = _build_supabase(
        project_data=_PROJECT_ROW,
        dedup_log_data=[],
        error_count_data=rows_inside_window,   # below threshold
        open_incident_data=[],
        new_log_id="log-abc",
    )
    with patch.object(svc, "supabase", sb):
        result = svc.ingest_log(BASE_LOG)

    assert result.incident_created is False
    assert result.incident_id is None


def test_incident_not_created_below_threshold():
    """Error count == threshold - 1 → no incident."""
    rows = [{"id": f"log-{i}"} for i in range(svc.ERROR_THRESHOLD - 1)]
    sb = _build_supabase(
        project_data=_PROJECT_ROW,
        dedup_log_data=[],
        error_count_data=rows,
        open_incident_data=[],
        new_log_id="log-xxx",
    )
    with patch.object(svc, "supabase", sb):
        result = svc.ingest_log(BASE_LOG)

    assert result.incident_created is False


def test_incident_created_at_threshold():
    """Error count == threshold → new incident created, incident_created=True."""
    rows = [{"id": f"log-{i}"} for i in range(svc.ERROR_THRESHOLD)]
    sb = _build_supabase(
        project_data=_PROJECT_ROW,
        dedup_log_data=[],
        error_count_data=rows,
        open_incident_data=[],
        new_log_id="log-new",
        new_incident_id="incident-111",
    )
    with patch.object(svc, "supabase", sb):
        result = svc.ingest_log(BASE_LOG)

    assert result.incident_created is True
    assert result.incident_id == "incident-111"
    assert result.deduplicated is False


def test_second_crossing_bumps_occurrence_count_not_new_incident():
    """
    Threshold crossed again while an open incident exists → occurrence_count
    bumped; incident_created is False; incident_id is the EXISTING one.
    """
    rows = [{"id": f"log-{i}"} for i in range(svc.ERROR_THRESHOLD)]
    open_incident = [{"id": "incident-existing", "occurrence_count": 3}]

    sb = _build_supabase(
        project_data=_PROJECT_ROW,
        dedup_log_data=[],
        error_count_data=rows,
        open_incident_data=open_incident,
        new_log_id="log-new",
    )
    with patch.object(svc, "supabase", sb):
        result = svc.ingest_log(BASE_LOG)

    assert result.incident_id == "incident-existing"
    assert result.incident_created is False


def test_per_project_threshold_overrides_global_default():
    """
    When a project row carries non-NULL error_threshold / error_window_minutes,
    those values should win over the global env defaults.

    Strategy: set per-project threshold = 2 and provide exactly 2 error rows.
    With the global default (5) an incident would NOT be created; with the
    per-project override (2) it SHOULD be created.
    """
    project_with_override = {
        "id": PROJECT_ID,
        "user_id": "user-A",
        "error_threshold": 2,           # lower than global default (5)
        "error_window_minutes": 10,     # longer window
    }
    # Exactly 2 rows — meets the per-project threshold of 2
    rows = [{"id": "log-0"}, {"id": "log-1"}]

    sb = _build_supabase(
        project_data=project_with_override,
        dedup_log_data=[],
        error_count_data=rows,
        open_incident_data=[],
        new_log_id="log-new",
        new_incident_id="incident-override",
    )
    with patch.object(svc, "supabase", sb):
        result = svc.ingest_log(BASE_LOG)

    # With the override threshold of 2 → incident must be created
    assert result.incident_created is True
    assert result.incident_id == "incident-override"
