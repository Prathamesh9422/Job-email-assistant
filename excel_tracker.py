"""Write-through mirror of the queue into a durable tracker.xlsx."""
from datetime import datetime, timezone

from openpyxl import Workbook, load_workbook

from config import TRACKER_FILE

HEADERS = [
    "date_processed",
    "gmail_message_id",
    "subject",
    "company",
    "role",
    "hr_email_used",
    "status",
    "resume_filename",
    "sent_at",
]


def _load_or_create():
    if TRACKER_FILE.exists():
        wb = load_workbook(TRACKER_FILE)
        ws = wb.active
    else:
        wb = Workbook()
        ws = wb.active
        ws.append(HEADERS)
    return wb, ws


def upsert_tracker_row(queue_row: dict) -> None:
    wb, ws = _load_or_create()

    message_id_col = HEADERS.index("gmail_message_id") + 1
    target_row = None
    for r in range(2, ws.max_row + 1):
        if ws.cell(row=r, column=message_id_col).value == queue_row["gmail_message_id"]:
            target_row = r
            break

    values = [
        datetime.now(timezone.utc).isoformat(),
        queue_row.get("gmail_message_id"),
        queue_row.get("subject"),
        queue_row.get("company"),
        queue_row.get("role"),
        queue_row.get("hr_email"),
        queue_row.get("status"),
        queue_row.get("resume_filename"),
        queue_row.get("sent_at"),
    ]

    if target_row is None:
        ws.append(values)
    else:
        for col, value in enumerate(values, start=1):
            ws.cell(row=target_row, column=col, value=value)

    wb.save(TRACKER_FILE)
