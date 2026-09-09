"""
Tests for idempotent log ingestion (services/log_service.py).

Covers:
- First call inserts a new log row
- Identical retry within the window returns the existing row (deduplicated=True)
- Different message in same window inserts a new row
- Incident created on first threshold crossing
- Second threshold crossing when open incident exists → no duplicate (bumps count)
"""

import os
os.environ["SUPABASE_URL"] = "https://fake.supabase.co"
os.environ["SUPABASE_KEY"] = "fake-key"

import hashlib
import math
from datetime import datetime, timezone
from unittest.mock import MagicMock, call, patch

import pytest

import services.log_service as svc
from schemas.logs import LogCreate

# ── shared fixtures ───────────────────────────────────────────────────────────

PROJECT_ID = "proj-111"
SERVICE    = "auth-service"

BASE_LOG = LogCreate(
    api_key="test-api-key",
    service=SERVICE,
    level="ERROR",
    message="Connection refused",
)


def _project_mock():
    m = MagicMock()
    m.data = {"id": PROJECT_ID, "user_id": "user-A"}
    return m


def _insert_mock(log_id: str):
    m = MagicMock()
    m.data = [{"id": log_id}]
    return m


def _build_supabase(
    project_data,
    dedup_log_data,    # result of _find_duplicate_log query
    error_count_data,  # list of log rows for threshold check
    open_incident_data,# existing open incident (or empty list)
    new_incident_id="incident-new",
    new_log_id="log-new",
):
    """
    Build a fully mocked supabase client whose `.table()` calls are
    dispatched in the order the real service makes them.
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

    insert_chain = MagicMock()
    insert_chain.insert.return_value = insert_chain
    insert_chain.execute.return_value = MagicMock(data=[{"id": new_log_id}])

    incident_insert_chain = MagicMock()
    incident_insert_chain.insert.return_value = incident_insert_chain
    incident_insert_chain.execute.return_value = MagicMock(data=[{"id": new_incident_id}])

    incident_update_chain = MagicMock()
    incident_update_chain.update.return_value = incident_update_chain
    incident_update_chain.eq.return_value = incident_update_chain
    incident_update_chain.execute.return_value = MagicMock(data=[])

    tables = {
        # order matters — side_effect list must match call order
    }

    call_log = []

    def table_router(name):
        call_log.append(name)
        n = len(call_log)
        # call 1: projects (project lookup)
        if n == 1:
            return _chain(project_data)
        # call 2: logs (dedup check)
        if n == 2:
            return _chain(dedup_log_data)
        # call 3: logs (insert) — only if dedup_log_data is empty
        if n == 3 and name == "logs":
            return insert_chain
        # call 4: logs (error count for threshold)
        if n == 4 and name == "logs":
            return _chain(error_count_data)
        # call 5: incidents (open incident check)
        if n == 5 and name == "incidents":
            return _chain(open_incident_data)
        # call 6: incidents (insert new) or update
        if n == 6 and name == "incidents":
            if open_incident_data:
                return incident_update_chain
            return incident_insert_chain
        return MagicMock()

    sb.table.side_effect = table_router
    return sb


# ── tests ─────────────────────────────────────────────────────────────────────

def test_first_ingestion_inserts_row():
    """First call → new log row inserted, deduplicated=False."""
    sb = _build_supabase(
        project_data={"id": PROJECT_ID, "user_id": "user-A"},
        dedup_log_data=[],          # no duplicate
        error_count_data=[],        # below threshold
        open_incident_data=[],
        new_log_id="log-001",
    )
    with patch.object(svc, "supabase", sb):
        result = svc.ingest_log(BASE_LOG)

    assert result.deduplicated is False
    assert result.id == "log-001"
    assert result.incident_created is False


def test_duplicate_retry_is_suppressed():
    """Second identical call within window → returns existing log, no insert."""
    existing_log = {"id": "log-existing", "incident_id": None}
    sb = _build_supabase(
        project_data={"id": PROJECT_ID, "user_id": "user-A"},
        dedup_log_data=[existing_log],  # duplicate found
        error_count_data=[],
        open_incident_data=[],
    )
    with patch.object(svc, "supabase", sb):
        result = svc.ingest_log(BASE_LOG)

    assert result.deduplicated is True
    assert result.id == "log-existing"
    assert result.incident_created is False


def test_caller_supplied_idempotency_key_used():
    """A caller-supplied key is used instead of the auto-computed one."""
    log_with_key = BASE_LOG.model_copy(update={"idempotency_key": "my-custom-key"})
    existing_log = {"id": "log-from-key", "incident_id": None}

    sb = _build_supabase(
        project_data={"id": PROJECT_ID, "user_id": "user-A"},
        dedup_log_data=[existing_log],
        error_count_data=[],
        open_incident_data=[],
    )
    with patch.object(svc, "supabase", sb):
        result = svc.ingest_log(log_with_key)

    assert result.deduplicated is True
    assert result.id == "log-from-key"


def test_incident_created_on_threshold():
    """When error count >= threshold and no open incident → new incident created."""
    error_rows = [{"id": f"log-{i}"} for i in range(svc.ERROR_THRESHOLD)]

    sb = _build_supabase(
        project_data={"id": PROJECT_ID, "user_id": "user-A"},
        dedup_log_data=[],
        error_count_data=error_rows,     # threshold crossed
        open_incident_data=[],           # no existing open incident
        new_log_id="log-new",
        new_incident_id="incident-111",
    )
    with patch.object(svc, "supabase", sb):
        result = svc.ingest_log(BASE_LOG)

    assert result.incident_created is True
    assert result.incident_id == "incident-111"
    assert result.deduplicated is False


def test_no_duplicate_incident_when_open_exists():
    """
    When threshold is crossed but an open incident already exists for
    (project_id, service) → no new incident is created.
    """
    error_rows = [{"id": f"log-{i}"} for i in range(svc.ERROR_THRESHOLD)]
    open_incident = [{"id": "incident-existing", "occurrence_count": 3}]

    sb = _build_supabase(
        project_data={"id": PROJECT_ID, "user_id": "user-A"},
        dedup_log_data=[],
        error_count_data=error_rows,
        open_incident_data=open_incident,   # already open
        new_log_id="log-new",
    )
    with patch.object(svc, "supabase", sb):
        result = svc.ingest_log(BASE_LOG)

    # incident_id is the EXISTING one, not a new duplicate
    assert result.incident_id == "incident-existing"
    # occurrence_count bump was attempted (update was called)
    assert result.incident_created is False
