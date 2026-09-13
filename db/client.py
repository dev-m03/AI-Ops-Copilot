"""
Supabase client — lazy initialization.

WHY lazy and not eager?
───────────────────────
The original code called create_client() at module load time:

    supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)   # ← eager

This caused every test that imported any service module to immediately
attempt a real Supabase connection, crashing with:
    SupabaseException: supabase_key is required

Even with SUPABASE_URL / SUPABASE_SERVICE_KEY set to fake values in the
test env, the SDK validates the key is non-empty at construction time.

The fix: wrap the client in a function and cache the result.
The first real call to `get_supabase()` creates the client; all subsequent
calls return the cached instance.  Tests that patch `supabase` in the
service modules never trigger this function at all.

Usage (unchanged for callers that already did `from db.client import supabase`):
    from db.client import supabase    ← still works — supabase is now a proxy object
OR the explicit getter:
    from db.client import get_supabase
    client = get_supabase()
"""
from __future__ import annotations

from supabase import Client, create_client

from core.config import SUPABASE_SERVICE_KEY, SUPABASE_URL

_client: Client | None = None


def get_supabase() -> Client:
    """Return the singleton Supabase client, creating it on first call."""
    global _client
    if _client is None:
        if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set before "
                "the Supabase client is used."
            )
        _client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    return _client


class _LazySupabase:
    """
    Transparent proxy so that existing code using:
        from db.client import supabase
        supabase.table(...)
    continues to work without any changes.

    The real client is created only when an attribute is first accessed.
    """

    def __getattr__(self, name: str):
        return getattr(get_supabase(), name)


# Drop-in replacement: code that does `from db.client import supabase` keeps working
supabase = _LazySupabase()
