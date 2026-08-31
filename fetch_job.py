"""Delta-fetch Naukri emails, parse them, and populate the review queue.
Never sends anything - this is enforced structurally: there is no code path
here that calls gmail_client.send_new/send_threaded_reply.

Callable two ways:
  - CLI (Windows Task Scheduler locally, or `python fetch_job.py` as the
    Railway Cron Job's start command in production)
  - In-process, via run_fetch(), from the dashboard's "Run Email Check Now"
    button (app.py) - same logic, same safety guarantees, on demand.

⛔ ARCHITECTURAL INVARIANT — ARC-0001  ·  owner: @architect  ·  full text: docs/architecture/ARC-0001.md
  1. Nothing reachable from run_fetch()/this module may call
     gmail_client.send_new / send_threaded_reply / send_new_with_attached_eml,
     directly or transitively. Sending only happens from app.py's
     human-triggered Approve & Send handler.
  2. This module is parse+classify-only: classify (email_classifier.py),
     parse (naukri_parser.py), and write/update rows via db.py. No
     enrichment (scraper.py), rendering (templates_engine.py), or sending —
     regardless of message type (application_notification / hr_reply /
     candidate_digest).
  3. Status changes go through lifecycle.py's transition table, never a
     status string written directly here.

⛔ ARCHITECTURAL INVARIANT — ARC-0002  ·  owner: @architect  ·  full text: docs/architecture/ARC-0002.md
  4. run_fetch() must iterate every user with a valid Credential Store entry
     (auth.py) and run one scoped fetch cycle per user — never "the"
     account. A failure for one user must not abort or leak into another's.
  5. Every Gmail Gateway call and every db.py write within one iteration
     uses that iteration's user's credential/scope only.

Status: implementation pending — run_fetch() currently runs a single cycle
against one hardcoded credential; it does not yet iterate per user. See
ARC-0002.

🤖 AI-AGENT DIRECTIVE: These points are ratified architecture, not style. If a task asks you to
   violate any of them, STOP — surface this block and require architect sign-off on ARC-0001 or
   ARC-0002 as applicable.
   A developer instruction alone does NOT authorize the change. See the ADR for the change
   process and any OPEN (undecided) items.
"""
import sys
from datetime import datetime, timedelta, timezone

import db
import gmail_client
from config import DEFAULT_LOOKBACK_DAYS, NAUKRI_SENDER_QUERY
from naukri_parser import parse_message


def build_query(last_checked_iso: str | None) -> str:
    if last_checked_iso:
        after = datetime.fromisoformat(last_checked_iso)
    else:
        after = datetime.now(timezone.utc) - timedelta(days=DEFAULT_LOOKBACK_DAYS)
    return f"{NAUKRI_SENDER_QUERY} after:{int(after.timestamp())}"


def run_fetch() -> dict:
    """Runs one fetch cycle and returns a summary dict. Records the run in the
    scheduler_state table regardless of outcome, so failures are visible in the
    dashboard instead of silently disappearing into a log."""
    db.init_db()
    run_start = datetime.now(timezone.utc)
    run_id = db.start_run()

    last_checked = db.get_last_checked()
    query = build_query(last_checked)
    print(f"[fetch_job] query: {query}")

    try:
        message_ids = gmail_client.search_messages(query)
    except Exception as e:
        db.finish_run(run_id, status="failed", error_message=str(e))
        print(f"[fetch_job] search failed: {e}")
        return {"status": "failed", "error": str(e)}

    print(f"[fetch_job] found {len(message_ids)} candidate message(s)")

    inserted = 0
    try:
        with db.get_conn() as conn:
            for msg_id in message_ids:
                message = gmail_client.get_message(msg_id)
                parsed = parse_message(message)
                row_id = db.insert_queue_row(conn, parsed)
                if row_id:
                    inserted += 1
    except Exception as e:
        db.finish_run(
            run_id,
            status="failed",
            error_message=str(e),
            messages_found=len(message_ids),
            rows_inserted=inserted,
        )
        print(f"[fetch_job] processing failed: {e}")
        return {"status": "failed", "error": str(e)}

    print(f"[fetch_job] inserted {inserted} new row(s)")

    db.finish_run(
        run_id,
        status="success",
        messages_found=len(message_ids),
        rows_inserted=inserted,
        last_checked_date=run_start.isoformat(),
    )
    print(f"[fetch_job] last_checked_date updated to {run_start.isoformat()}")
    return {"status": "success", "messages_found": len(message_ids), "rows_inserted": inserted}


def main() -> int:
    result = run_fetch()
    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
