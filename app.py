"""FastAPI backend + UI server. This is the ONLY place emails are ever sent —
always via an explicit user action (Approve & Send button).

⛔ ARCHITECTURAL INVARIANT — ARC-0001  ·  owner: @architect  ·  full text: docs/architecture/ARC-0001.md
  1. api_send() is the only call site for gmail_client.send_* in the whole
     app, and it must only run in response to an explicit user request (the
     dashboard's Approve & Send action) — never on a schedule or automatically.
  2. All Gmail API access goes through gmail_client.py; all persistence goes
     through db.py. Don't build credentials or SQL here.
  3. Enriching a candidate_digest row (scraper.py) and applying to it is a
     human-triggered action here, same as sending — never automatic.

⛔ ARCHITECTURAL INVARIANT — ARC-0002  ·  owner: @architect  ·  full text: docs/architecture/ARC-0002.md
  4. Every request runs in a Session bound to one signed-in user (auth.py).
     api_send() and every db.py read/write here must use that Session's
     User Scope — never another user's, never a global credential.
  5. The Sign-In Flow (auth.py) is the only way a user's identity enters
     this app — no bypassing it with a hardcoded/shared account.

⛔ ARCHITECTURAL INVARIANT — ARC-0003  ·  owner: @architect  ·  full text: docs/architecture/ARC-0003.md
  6. api_list_queue()'s default listing must include every non-terminal
     status (terminal = offer/rejected/skipped only) — a row must not drop
     out of the default view just because it was sent.
  7. api_send() must capture an immutable Sent Record (subject/body/
     timestamp actually transmitted) distinct from the editable
     final_subject/final_body draft; later draft edits must never mutate a
     past Sent Record.
  8. Manual override of an Enrichment-sourced field (hr_email, company,
     ...) must remain possible from here (source="manual") whenever
     automated enrichment fails to resolve it — never a database-only fix.

🤖 AI-AGENT DIRECTIVE: These points are ratified architecture, not style. If a task asks you to
   violate any of them, STOP — surface this block and require architect sign-off on ARC-0001,
   ARC-0002, or ARC-0003 as applicable.
   A developer instruction alone does NOT authorize the change. See the ADR for the change
   process and any OPEN (undecided) items.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

import auth
import db
import excel_tracker
import fetch_job
import gmail_client
import lifecycle
import scraper
from config import (
    RESUMES_DIR,
    SESSION_SECRET_KEY,
    STATIC_DIR,
    TRACKER_FILE,
    ACTIONABLE_STATUSES,
    STATUS_FAILED,
    STATUS_NEEDS_INFO,
    STATUS_READY,
    STATUS_SENT,
    STATUS_SKIPPED,
    SOURCE_SCRAPED,
    TEMPLATE_COLD_OUTREACH,
    TEMPLATE_COVER_LETTER,
    TEMPLATE_REPLY_TO_NAUKRI,
)

VALID_TEMPLATES = (TEMPLATE_REPLY_TO_NAUKRI, TEMPLATE_COLD_OUTREACH, TEMPLATE_COVER_LETTER)
from templates_engine import render_template

# The daily fetch job's cron schedule, so the dashboard can show when the next
# run is expected. Keep in sync with the Railway Cron Job's schedule (30 14 * * * UTC).
NEXT_RUN_HOUR_UTC = 14
NEXT_RUN_MINUTE_UTC = 30

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET_KEY)

RESUMES_DIR.mkdir(parents=True, exist_ok=True)
TRACKER_FILE.parent.mkdir(parents=True, exist_ok=True)
db.init_db()


def latest_resume() -> Optional[Path]:
    pdfs = list(RESUMES_DIR.glob("*.pdf"))
    if not pdfs:
        return None
    return max(pdfs, key=lambda p: p.stat().st_mtime)


def _clean_company(row: dict) -> Optional[str]:
    """The company/role fields sometimes both get filled from the same HTML fallback text
    (e.g. a recruiter-broadcast email with no company disclosed) - drop company if it's
    just a duplicate/superset of the role text rather than a real, distinct company name."""
    company = row.get("company")
    role = row.get("role")
    if not company:
        return None
    if role and (company == role or role in company or company in role):
        return None
    return company


def build_template_context(row: dict) -> dict:
    company = _clean_company(row)
    return {
        "company": company or "the company",
        "role": row.get("role") or "the role",
        "hr_email": row.get("hr_email"),
        "hr_name": row.get("hr_name"),
        "sender_name": "Prathamesh Patil",
        "job_link": row.get("job_link"),
    }


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/home")
def home_page():
    """Public, static, no-auth page describing the app - used as the OAuth
    consent screen's 'Application home page'. Serves no Gmail or queue data."""
    return FileResponse(STATIC_DIR / "home.html")


@app.get("/privacy")
def privacy_page():
    """Public, static, no-auth privacy policy - used as the OAuth consent
    screen's 'Application privacy policy link'. Serves no Gmail or queue data."""
    return FileResponse(STATIC_DIR / "privacy.html")


@app.get("/api/health")
def health():
    return {"ok": True}


# --- Sign in with Google (ARC-0002) ---


@app.get("/auth/login")
def auth_login(request: Request):
    return auth.start_sign_in(request)


@app.get("/auth/callback", name="auth_callback")
def auth_callback(request: Request):
    return auth.handle_callback(request)


@app.post("/auth/logout")
def auth_logout(request: Request):
    auth.logout(request)
    return RedirectResponse("/")


@app.get("/api/me")
def api_me(current_user: dict = Depends(auth.require_user)):
    return {"id": current_user["id"], "email": current_user["email"]}


def _next_expected_run_utc() -> str:
    now = datetime.now(timezone.utc)
    target = now.replace(hour=NEXT_RUN_HOUR_UTC, minute=NEXT_RUN_MINUTE_UTC, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target.isoformat()


@app.get("/api/scheduler/status")
def scheduler_status(current_user: dict = Depends(auth.require_user)):
    latest = db.get_latest_run(current_user["id"])
    return {
        "last_run_at": latest.get("run_started_at") if latest else None,
        "last_run_finished_at": latest.get("run_finished_at") if latest else None,
        "last_run_status": latest.get("status") if latest else None,
        "last_run_error": latest.get("error_message") if latest else None,
        "messages_found": latest.get("messages_found") if latest else None,
        "processed_count": latest.get("rows_inserted") if latest else None,
        "next_expected_run_utc": _next_expected_run_utc(),
    }


@app.post("/api/scheduler/run-now")
def scheduler_run_now(current_user: dict = Depends(auth.require_user)):
    """Manual trigger for testing - runs the exact same triage logic as the
    scheduled cron job, scoped to the signed-in user only. Never sends email
    (fetch_job.run_fetch_for_user has no send code path)."""
    return fetch_job.run_fetch_for_user(current_user)


@app.get("/api/resume")
def get_resume(current_user: dict = Depends(auth.require_user)):
    resume = latest_resume()
    return {"resume_filename": resume.name if resume else None}


@app.get("/api/queue")
def api_list_queue(status: Optional[str] = None, current_user: dict = Depends(auth.require_user)):
    statuses = status.split(",") if status else list(ACTIONABLE_STATUSES)
    return db.list_queue(current_user["id"], statuses)


@app.get("/api/queue/{row_id}")
def api_get_queue_row(row_id: int, current_user: dict = Depends(auth.require_user)):
    row = db.get_queue_row(current_user["id"], row_id)
    if not row:
        raise HTTPException(404, "not found")
    return row


class PatchBody(BaseModel):
    hr_email: Optional[str] = None
    hr_name: Optional[str] = None
    company: Optional[str] = None
    template_used: Optional[str] = None


@app.patch("/api/queue/{row_id}")
def api_patch_queue_row(row_id: int, body: PatchBody, current_user: dict = Depends(auth.require_user)):
    row = db.get_queue_row(current_user["id"], row_id)
    if not row:
        raise HTTPException(404, "not found")
    fields = {}
    if body.hr_email is not None:
        fields["hr_email"] = body.hr_email
        fields["hr_email_source"] = "manual"
        fields["status"] = STATUS_READY if body.hr_email else STATUS_NEEDS_INFO
    if body.hr_name is not None:
        fields["hr_name"] = body.hr_name
    if body.company is not None:
        fields["company"] = body.company
        fields["company_source"] = "manual"
    if body.template_used is not None:
        fields["template_used"] = body.template_used
    db.update_queue_row(current_user["id"], row_id, fields)
    return db.get_queue_row(current_user["id"], row_id)


@app.post("/api/queue/{row_id}/scrape")
def api_scrape(row_id: int, current_user: dict = Depends(auth.require_user)):
    row = db.get_queue_row(current_user["id"], row_id)
    if not row:
        raise HTTPException(404, "not found")
    if not row.get("company"):
        raise HTTPException(400, "no company name on this row to scrape for")

    candidates = scraper.scrape_company_emails(row["company"])
    db.record_scrape_attempt(current_user["id"], row_id, None, candidates, success=bool(candidates))

    if candidates:
        db.update_queue_row(
            current_user["id"],
            row_id,
            {
                "hr_email": candidates[0],
                "hr_email_source": SOURCE_SCRAPED,
                "hr_email_confidence": "low",
            },
        )
    return {"candidates": candidates, "row": db.get_queue_row(current_user["id"], row_id)}


class PreviewBody(BaseModel):
    template: str


@app.post("/api/queue/{row_id}/preview")
def api_preview(row_id: int, body: PreviewBody, current_user: dict = Depends(auth.require_user)):
    row = db.get_queue_row(current_user["id"], row_id)
    if not row:
        raise HTTPException(404, "not found")
    if body.template not in VALID_TEMPLATES:
        raise HTTPException(400, "unknown template")
    context = build_template_context(row)
    return render_template(body.template, context)


@app.get("/api/queue/{row_id}/final")
def api_get_final(row_id: int, current_user: dict = Depends(auth.require_user)):
    row = db.get_queue_row(current_user["id"], row_id)
    if not row:
        raise HTTPException(404, "not found")
    if not row.get("final_body"):
        return {"subject": None, "body": None}
    return {"subject": row.get("final_subject"), "body": row.get("final_body")}


class FinalizeBody(BaseModel):
    subject: str
    body: str


@app.post("/api/queue/{row_id}/finalize")
def api_finalize(row_id: int, body: FinalizeBody, current_user: dict = Depends(auth.require_user)):
    row = db.get_queue_row(current_user["id"], row_id)
    if not row:
        raise HTTPException(404, "not found")
    db.update_queue_row(current_user["id"], row_id, {"final_subject": body.subject, "final_body": body.body})
    return db.get_queue_row(current_user["id"], row_id)


@app.post("/api/queue/{row_id}/send")
def api_send(row_id: int, current_user: dict = Depends(auth.require_user)):
    row = db.get_queue_row(current_user["id"], row_id)
    if not row:
        raise HTTPException(404, "not found")
    if not row.get("hr_email"):
        raise HTTPException(400, "no hr_email set on this row")
    template_used = row.get("template_used") or TEMPLATE_REPLY_TO_NAUKRI

    credentials = auth.get_credential_for_user(current_user["id"])
    resume = latest_resume()
    if row.get("final_body"):
        rendered = {"subject": row.get("final_subject") or "", "body": row["final_body"]}
    else:
        context = build_template_context(row)
        rendered = render_template(template_used, context)

    try:
        if template_used == TEMPLATE_REPLY_TO_NAUKRI:
            original_message = gmail_client.get_message(credentials, row["gmail_message_id"])
            result = gmail_client.send_threaded_reply(
                credentials,
                original_message,
                to=row["hr_email"],
                subject=rendered["subject"],
                body_text=rendered["body"],
                attachment_path=resume,
            )
        else:
            result = gmail_client.send_new(
                credentials,
                to=row["hr_email"],
                subject=rendered["subject"],
                body_text=rendered["body"],
                attachment_path=resume,
            )
    except Exception as e:
        db.update_queue_row(current_user["id"], row_id, {"status": STATUS_FAILED, "error_message": str(e)})
        excel_tracker.upsert_tracker_row(db.get_queue_row(current_user["id"], row_id))
        raise HTTPException(500, f"send failed: {e}")

    transition_fields = lifecycle.apply_transition(row, "send")
    db.update_queue_row(
        current_user["id"],
        row_id,
        {
            **transition_fields,
            "resume_filename": resume.name if resume else None,
            "template_used": template_used,
        },
    )
    # Immutable Sent Record of exactly what was transmitted (ARC-0003 invariant 5),
    # kept distinct from the still-editable final_subject/final_body draft.
    db.insert_sent_record(current_user["id"], row_id, rendered["subject"], rendered["body"])
    updated_row = db.get_queue_row(current_user["id"], row_id)
    excel_tracker.upsert_tracker_row(updated_row)
    return {"result": result, "row": updated_row}


@app.get("/api/queue/{row_id}/sent-records")
def api_list_sent_records(row_id: int, current_user: dict = Depends(auth.require_user)):
    row = db.get_queue_row(current_user["id"], row_id)
    if not row:
        raise HTTPException(404, "not found")
    return db.list_sent_records(current_user["id"], row_id)


class AdvanceBody(BaseModel):
    event: str


@app.post("/api/queue/{row_id}/advance")
def api_advance(row_id: int, body: AdvanceBody, current_user: dict = Depends(auth.require_user)):
    """Human-triggered lifecycle progress (HR replied / interview scheduled /
    rejected / offer) - the only path to these statuses today, since
    automated HR-reply classification (ARC-0001) isn't implemented yet."""
    row = db.get_queue_row(current_user["id"], row_id)
    if not row:
        raise HTTPException(404, "not found")
    try:
        fields = lifecycle.apply_transition(row, body.event)
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.update_queue_row(current_user["id"], row_id, fields)
    updated_row = db.get_queue_row(current_user["id"], row_id)
    excel_tracker.upsert_tracker_row(updated_row)
    return updated_row


@app.post("/api/queue/{row_id}/skip")
def api_skip(row_id: int, current_user: dict = Depends(auth.require_user)):
    row = db.get_queue_row(current_user["id"], row_id)
    if not row:
        raise HTTPException(404, "not found")
    try:
        fields = lifecycle.apply_transition(row, "skip")
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.update_queue_row(current_user["id"], row_id, fields)
    updated_row = db.get_queue_row(current_user["id"], row_id)
    excel_tracker.upsert_tracker_row(updated_row)
    return updated_row


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
