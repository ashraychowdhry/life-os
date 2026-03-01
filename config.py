import os
from dotenv import load_dotenv

load_dotenv()

# Database
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost/lifeos")

# Whoop OAuth2
WHOOP_CLIENT_ID = os.getenv("WHOOP_CLIENT_ID")
WHOOP_CLIENT_SECRET = os.getenv("WHOOP_CLIENT_SECRET")
WHOOP_REDIRECT_URI = os.getenv("WHOOP_REDIRECT_URI", "http://localhost:8080/callback")
WHOOP_BASE_URL_V1 = "https://api.prod.whoop.com/developer/v1"
WHOOP_BASE_URL = "https://api.prod.whoop.com/developer/v2"
WHOOP_AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
WHOOP_TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
WHOOP_SCOPES = [
    "read:recovery",
    "read:cycles",
    "read:workout",
    "read:sleep",
    "read:profile",
    "read:body_measurement",
]

# Oura
OURA_PERSONAL_ACCESS_TOKEN = os.getenv("OURA_PERSONAL_ACCESS_TOKEN")
OURA_BASE_URL = "https://api.ouraring.com/v2/usercollection"

# Anthropic (for AI analysis)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# Gemini (for AI analysis)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# OpenAI (fallback for AI analysis)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
