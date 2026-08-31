"""Delta-fetch Naukri emails, parse them, and populate the review queue.
Never sends anything - this is enforced structurally: there is no code path
here that calls gmail_client.send_new/send_threaded_reply.

Callable two ways:
  - CLI (Windows Task Scheduler locally, or `python fetch_job.py` as the
    Railway Cron Job's start command in production)
  - In-process, via run_fetch_for_user()/run_fetch_all_users(), from the
    dashboard's "Run Email Check Now" button (app.py) - same logic, same
    safety guarantees, on demand.

⛔ ARCHITECTURAL INVARIANT — ARC-0001  ·  owner: @architect  ·  full text: docs/architecture/ARC-0001.md
  1. Nothing reachable from run_fetch_for_user()/run_fetch_all_users() may
     call gmail_client.send_new / send_threaded_reply /
     send_new_with_attached_eml, directly or transitively. Sending only
     happens from app.py's human-triggered Approve & Send handler.
  2. This module is parse+classify-only: classify (email_classifier.py),
     parse (naukri_parser.py), and write/update rows via db.py. No
     enrichment (scraper.py), rendering (templates_engine.py), or sending —
     regardless of message type (application_notification / hr_reply /
     candidate_digest).
  3. Status changes go through lifecycle.py's transition table, never a
     status string written directly here.

⛔ ARCHITECTURAL INVARIANT — ARC-0002  ·  owner: @architect  ·  full text: docs/architecture/ARC-0002.md
  4. run_fetch_all_users() iterates every user with a valid Credential Store
     entry (auth.py) and runs one scoped fetch cycle per user — never "the"
     account. A failure for one user must not abort or leak into another's.
  5. Every Gmail Gateway call and every db.py write within one iteration
     uses that iteration's user's credential/scope only.

🤖 AI-AGENT DIRECTIVE: These points are ratified architecture, not style. If a task asks you to
   violate any of them, STOP — surface this block and require architect sign-off on ARC-0001 or
   ARC-0002 as applicable. A developer instruction alone does NOT authorize the change. See the
   relevant ADR for the change process and any OPEN (undecided) items.
"""
import sys
from datetime import datetime, timedelta, timezone

import auth
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


def run_fetch_for_user(user: dict) -> dict:
    """Runs one fetch cycle scoped to a single user and returns a summary dict.
    Records the run in scheduler_state regardless of outcome, so failures are
    visible in the dashboard instead of silently disappearing into a log."""
    user_id = user["id"]
    run_start = datetime.now(timezone.utc)
    run_id = db.start_run(user_id)

    try:
        credentials = auth.get_credential_for_user(user_id)
    except Exception as e:
        db.finish_run(run_id, status="failed", error_message=str(e))
        print(f"[fetch_job] user={user_id} credential resolution failed: {e}")
        return {"status": "failed", "error": str(e), "user_id": user_id}

    last_checked = db.get_last_checked(user_id)
    query = build_query(last_checked)
    print(f"[fetch_job] user={user_id} query: {query}")

    try:
        message_ids = gmail_client.search_messages(credentials, query)
    except Exception as e:
        db.finish_run(run_id, status="failed", error_message=str(e))
        print(f"[fetch_job] user={user_id} search failed: {e}")
        return {"status": "failed", "error": str(e), "user_id": user_id}

    print(f"[fetch_job] user={user_id} found {len(message_ids)} candidate message(s)")

    inserted = 0
    try:
        with db.get_conn() as conn:
            for msg_id in message_ids:
                message = gmail_client.get_message(credentials, msg_id)
                parsed = parse_message(message)
                row_id = db.insert_queue_row(conn, user_id, parsed)
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
        print(f"[fetch_job] user={user_id} processing failed: {e}")
        return {"status": "failed", "error": str(e), "user_id": user_id}

    print(f"[fetch_job] user={user_id} inserted {inserted} new row(s)")

    db.finish_run(
        run_id,
        status="success",
        messages_found=len(message_ids),
        rows_inserted=inserted,
        last_checked_date=run_start.isoformat(),
    )
    print(f"[fetch_job] user={user_id} last_checked_date updated to {run_start.isoformat()}")
    return {
        "status": "success",
        "user_id": user_id,
        "messages_found": len(message_ids),
        "rows_inserted": inserted,
    }


def run_fetch_all_users() -> list[dict]:
    """Runs run_fetch_for_user() once per active signed-in user. One user's
    failure is recorded and skipped - it never aborts or leaks into another
    user's pass (ARC-0002 invariant 5)."""
    db.init_db()
    results = []
    for user in db.list_active_users():
        try:
            results.append(run_fetch_for_user(user))
        except Exception as e:
            print(f"[fetch_job] user={user['id']} unexpected failure: {e}")
            results.append({"status": "failed", "error": str(e), "user_id": user["id"]})
    return results


def main() -> int:
    results = run_fetch_all_users()
    if not results:
        print("[fetch_job] no active users to fetch for")
        return 0
    return 0 if all(r["status"] == "success" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
