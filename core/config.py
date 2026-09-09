"""
Application-wide configuration.

All values are read from environment variables with safe defaults so the
service works out of the box without a .env file.

Detection vs. AI — important distinction
─────────────────────────────────────────
  Incident DETECTION is purely threshold-based (error count in a time window).
  The LLM (Gemini via aiops-genai) is only invoked for ROOT CAUSE ANALYSIS
  *after* an incident already exists.  Detection itself is NOT AI-driven.
"""

import os

from dotenv import load_dotenv

load_dotenv()

# ── Supabase ──────────────────────────────────────────────────────────────────
SUPABASE_URL         = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

# ── AI / GenAI ────────────────────────────────────────────────────────────────
AI_PROVIDER_KEY = os.getenv("AI_PROVIDER_KEY")

# ── Incident detection (threshold-based, NOT AI) ──────────────────────────────
# Number of ERROR logs within ERROR_WINDOW_MINUTES that triggers an incident.
# Can be overridden per-project via the projects.error_threshold column (NULL
# means "use global default").
ERROR_THRESHOLD: int = int(os.getenv("ERROR_THRESHOLD", "5"))

# Sliding window used both for counting errors and for the dedup check.
ERROR_WINDOW_MINUTES: int = int(os.getenv("ERROR_WINDOW_MINUTES", "5"))

# Size of the time-bucket used to auto-compute an idempotency key when the
# caller doesn't supply one.  Should equal ERROR_WINDOW_MINUTES * 60.
DEDUP_BUCKET_SECONDS: int = int(os.getenv("DEDUP_BUCKET_SECONDS", "300"))
