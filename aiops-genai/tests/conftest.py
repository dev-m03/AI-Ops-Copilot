"""
conftest.py for aiops-genai/tests/

Inserts the aiops-genai/ directory at the front of sys.path so that
`import main` (the genai microservice module) works when pytest is
invoked from the repo root with:
    pytest aiops-genai/tests/
or from within the aiops-genai/ directory:
    pytest
"""
import sys
import os

# aiops-genai/ is the parent of this conftest's directory
_GENAI_DIR = os.path.join(os.path.dirname(__file__), "..")
if _GENAI_DIR not in sys.path:
    sys.path.insert(0, os.path.abspath(_GENAI_DIR))
