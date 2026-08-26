"""Shared paths and constants for the Naukri triage app."""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SECRET_DIR = BASE_DIR / "secret"


def _find_client_secret() -> Path:
    """Locate the OAuth client secret JSON, wherever it was saved under secret/."""
    if SECRET_DIR.is_dir():
        candidates = sorted(SECRET_DIR.glob("client_secret*.json"))
        if candidates:
            return candidates[0]
    return SECRET_DIR / "client_secret.json"


CLIENT_SECRET_FILE = _find_client_secret()
TOKEN_FILE = SECRET_DIR / "token.json"
STATE_FILE = BASE_DIR / "state.json"
DB_FILE = BASE_DIR / "queue.db"
TRACKER_FILE = BASE_DIR / "tracker.xlsx"
RESUMES_DIR = BASE_DIR / "resumes"
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

# OAuth
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

# Gmail search
NAUKRI_SENDER_QUERY = "from:naukri.com"
DEFAULT_LOOKBACK_DAYS = 5

# Status values for queue.status
STATUS_NEEDS_INFO = "needs_info"
STATUS_READY = "ready"
STATUS_SENT = "sent"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"
STATUS_DIGEST = "digest"

# hr_email_source values
SOURCE_HEADER = "email_header"
SOURCE_BODY = "email_body"
SOURCE_SCRAPED = "scraped"
SOURCE_MANUAL = "manual"
SOURCE_NONE = "none"

TEMPLATE_REPLY_TO_NAUKRI = "reply_to_naukri"
TEMPLATE_COLD_OUTREACH = "cold_outreach"
