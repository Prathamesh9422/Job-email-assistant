"""FastAPI backend + UI server. This is the ONLY place emails are ever sent —
always via an explicit user action (Approve & Send button)."""
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import db
import excel_tracker
import gmail_client
import scraper
from config import (
    RESUMES_DIR,
    STATIC_DIR,
    STATUS_FAILED,
    STATUS_NEEDS_INFO,
    STATUS_READY,
    STATUS_SENT,
    STATUS_SKIPPED,
    SOURCE_SCRAPED,
    TEMPLATE_COLD_OUTREACH,
    TEMPLATE_REPLY_TO_NAUKRI,
)
from templates_engine import render_template

app = FastAPI()
db.init_db()


def latest_resume() -> Optional[Path]:
    pdfs = list(RESUMES_DIR.glob("*.pdf"))
    if not pdfs:
        return None
    return max(pdfs, key=lambda p: p.stat().st_mtime)


def build_template_context(row: dict) -> dict:
    return {
        "company": row.get("company") or "the company",
        "role": row.get("role") or "the role",
        "hr_email": row.get("hr_email"),
        "hr_name": None,
        "sender_name": "Digvijay",
        "job_link": row.get("job_link"),
    }


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/resume")
def get_resume():
    resume = latest_resume()
    return {"resume_filename": resume.name if resume else None}


@app.get("/api/queue")
def api_list_queue(status: Optional[str] = None):
    statuses = status.split(",") if status else [STATUS_NEEDS_INFO, STATUS_READY]
    return db.list_queue(statuses)


@app.get("/api/queue/{row_id}")
def api_get_queue_row(row_id: int):
    row = db.get_queue_row(row_id)
    if not row:
        raise HTTPException(404, "not found")
    return row


class PatchBody(BaseModel):
    hr_email: Optional[str] = None
    template_used: Optional[str] = None


@app.patch("/api/queue/{row_id}")
def api_patch_queue_row(row_id: int, body: PatchBody):
    row = db.get_queue_row(row_id)
    if not row:
        raise HTTPException(404, "not found")
    fields = {}
    if body.hr_email is not None:
        fields["hr_email"] = body.hr_email
        fields["hr_email_source"] = "manual"
        fields["status"] = STATUS_READY if body.hr_email else STATUS_NEEDS_INFO
    if body.template_used is not None:
        fields["template_used"] = body.template_used
    db.update_queue_row(row_id, fields)
    return db.get_queue_row(row_id)


@app.post("/api/queue/{row_id}/scrape")
def api_scrape(row_id: int):
    row = db.get_queue_row(row_id)
    if not row:
        raise HTTPException(404, "not found")
    if not row.get("company"):
        raise HTTPException(400, "no company name on this row to scrape for")

    candidates = scraper.scrape_company_emails(row["company"])
    db.record_scrape_attempt(row_id, None, candidates, success=bool(candidates))

    if candidates:
        db.update_queue_row(
            row_id,
            {
                "hr_email": candidates[0],
                "hr_email_source": SOURCE_SCRAPED,
                "hr_email_confidence": "low",
            },
        )
    return {"candidates": candidates, "row": db.get_queue_row(row_id)}


class PreviewBody(BaseModel):
    template: str


@app.post("/api/queue/{row_id}/preview")
def api_preview(row_id: int, body: PreviewBody):
    row = db.get_queue_row(row_id)
    if not row:
        raise HTTPException(404, "not found")
    if body.template not in (TEMPLATE_REPLY_TO_NAUKRI, TEMPLATE_COLD_OUTREACH):
        raise HTTPException(400, "unknown template")
    context = build_template_context(row)
    return render_template(body.template, context)


@app.post("/api/queue/{row_id}/send")
def api_send(row_id: int):
    row = db.get_queue_row(row_id)
    if not row:
        raise HTTPException(404, "not found")
    if not row.get("hr_email"):
        raise HTTPException(400, "no hr_email set on this row")
    template_used = row.get("template_used") or TEMPLATE_REPLY_TO_NAUKRI

    resume = latest_resume()
    context = build_template_context(row)
    rendered = render_template(template_used, context)

    try:
        if template_used == TEMPLATE_REPLY_TO_NAUKRI:
            original_message = gmail_client.get_message(row["gmail_message_id"])
            result = gmail_client.send_threaded_reply(
                original_message,
                to=row["hr_email"],
                subject=rendered["subject"],
                body_text=rendered["body"],
                attachment_path=resume,
            )
        else:
            result = gmail_client.send_new(
                to=row["hr_email"],
                subject=rendered["subject"],
                body_text=rendered["body"],
                attachment_path=resume,
            )
    except Exception as e:
        db.update_queue_row(row_id, {"status": STATUS_FAILED, "error_message": str(e)})
        excel_tracker.upsert_tracker_row(db.get_queue_row(row_id))
        raise HTTPException(500, f"send failed: {e}")

    from datetime import datetime, timezone

    db.update_queue_row(
        row_id,
        {
            "status": STATUS_SENT,
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "resume_filename": resume.name if resume else None,
            "template_used": template_used,
        },
    )
    updated_row = db.get_queue_row(row_id)
    excel_tracker.upsert_tracker_row(updated_row)
    return {"result": result, "row": updated_row}


@app.post("/api/queue/{row_id}/skip")
def api_skip(row_id: int):
    row = db.get_queue_row(row_id)
    if not row:
        raise HTTPException(404, "not found")
    db.update_queue_row(row_id, {"status": STATUS_SKIPPED})
    updated_row = db.get_queue_row(row_id)
    excel_tracker.upsert_tracker_row(updated_row)
    return updated_row


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
