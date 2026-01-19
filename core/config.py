import os
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

AI_PROVIDER_KEY = os.getenv("AI_PROVIDER_KEY")
# Slack integration removed - use generic notification service instead
