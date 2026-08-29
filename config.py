"""Shared paths and constants for the Naukri triage app."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SECRET_DIR = BASE_DIR / "secret"

# DATA_DIR is where mutable/runtime data lives: locally this is the repo root
# (unchanged behavior); in production (Railway) it's set to a mounted Volume
# path (e.g. /data) so tracker.xlsx and the resume survive restarts/redeploys.
DATA_DIR = Path(os.environ.get("DATA_DIR", str(BASE_DIR)))


def _find_client_secret() -> Path:
    """Locate the OAuth client secret JSON, wherever it was saved under secret/."""
    if SECRET_DIR.is_dir():
        candidates = sorted(SECRET_DIR.glob("client_secret*.json"))
        if candidates:
            return candidates[0]
    return SECRET_DIR / "client_secret.json"


def _normalize_database_url(url: str) -> str:
    # Railway (and some other providers) hand out postgres:// URLs, but modern
    # SQLAlchemy/psycopg2 expect the postgresql:// scheme.
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


CLIENT_SECRET_FILE = _find_client_secret()
TOKEN_FILE = SECRET_DIR / "token.json"
DB_FILE = BASE_DIR / "queue.db"
TRACKER_FILE = DATA_DIR / "tracker.xlsx"
RESUMES_DIR = DATA_DIR / "resumes"
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

# Local dev (no DATABASE_URL set) keeps using the local SQLite file exactly as
# before. In production, Railway injects DATABASE_URL pointing at its managed
# Postgres plugin, shared by both the web service and the cron job.
DATABASE_URL = _normalize_database_url(
    os.environ.get("DATABASE_URL", f"sqlite:///{DB_FILE}")
)

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
TEMPLATE_COVER_LETTER = "cover_letter"
