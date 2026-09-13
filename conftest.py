# Root-level conftest.py
# ─────────────────────────────────────────────────────────────────────────────
# Having this file at the repo root (alongside pytest.ini) ensures pytest
# treats each subdirectory that contains a conftest.py or __init__.py as a
# proper package, avoiding "No module named 'tests.test_X'" collisions when
# tests/ and aiops-genai/tests/ are collected in the same session.
#
# This file intentionally left blank — its presence alone fixes the issue.
