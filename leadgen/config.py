import os
from dotenv import load_dotenv

load_dotenv()

GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
USER_AGENT = os.getenv("USER_AGENT", "MumbaiLeadEngine/0.1 (contact: you@example.com)")
DEFAULT_REGION = "IN"
REQUEST_TIMEOUT = 25
