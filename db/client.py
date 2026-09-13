from supabase import create_client

from core.config import SUPABASE_SERVICE_KEY, SUPABASE_URL

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
