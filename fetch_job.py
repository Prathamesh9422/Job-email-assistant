"""Daily entrypoint (run via Windows Task Scheduler): delta-fetch Naukri emails,
parse them, and populate the review queue. Never sends anything.
"""
import json
import sys
from datetime import datetime, timedelta, timezone

import db
import gmail_client
from config import DEFAULT_LOOKBACK_DAYS, NAUKRI_SENDER_QUERY, STATE_FILE
from naukri_parser import parse_message


def load_last_checked() -> datetime | None:
    if not STATE_FILE.exists():
        return None
    try:
        data = json.loads(STATE_FILE.read_text())
        return datetime.fromisoformat(data["last_checked_date"])
    except Exception:
        return None


def save_last_checked(dt: datetime) -> None:
    STATE_FILE.write_text(json.dumps({"last_checked_date": dt.isoformat()}))


def build_query(last_checked: datetime | None) -> str:
    after = last_checked or (datetime.now(timezone.utc) - timedelta(days=DEFAULT_LOOKBACK_DAYS))
    return f"{NAUKRI_SENDER_QUERY} after:{int(after.timestamp())}"


def main() -> int:
    run_start = datetime.now(timezone.utc)
    db.init_db()

    last_checked = load_last_checked()
    query = build_query(last_checked)
    print(f"[fetch_job] query: {query}")

    try:
        message_ids = gmail_client.search_messages(query)
    except FileNotFoundError as e:
        print(f"[fetch_job] {e}")
        return 1

    print(f"[fetch_job] found {len(message_ids)} candidate message(s)")

    inserted = 0
    with db.get_conn() as conn:
        for msg_id in message_ids:
            message = gmail_client.get_message(msg_id)
            parsed = parse_message(message)
            row_id = db.insert_queue_row(conn, parsed)
            if row_id:
                inserted += 1

    print(f"[fetch_job] inserted {inserted} new row(s)")

    save_last_checked(run_start)
    print(f"[fetch_job] last_checked_date updated to {run_start.isoformat()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
