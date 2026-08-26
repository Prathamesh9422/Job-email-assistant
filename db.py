"""SQLite access layer for the triage queue."""
import json
import sqlite3
from contextlib import contextmanager
from typing import Any, Iterable, Optional

from config import DB_FILE, STATUS_NEEDS_INFO, SOURCE_NONE

SCHEMA = """
CREATE TABLE IF NOT EXISTS queue (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    gmail_message_id    TEXT UNIQUE NOT NULL,
    gmail_thread_id     TEXT,
    received_at         TEXT NOT NULL,
    subject             TEXT,
    company             TEXT,
    role                TEXT,
    job_link            TEXT,
    digest_job_links    TEXT,
    hr_email            TEXT,
    hr_email_source     TEXT NOT NULL DEFAULT 'none',
    hr_email_confidence TEXT NOT NULL DEFAULT 'low',
    template_used       TEXT,
    status              TEXT NOT NULL DEFAULT 'needs_info',
    error_message       TEXT,
    resume_filename     TEXT,
    sent_at             TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_queue_status ON queue(status);

CREATE TABLE IF NOT EXISTS scrape_attempts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    queue_id      INTEGER NOT NULL REFERENCES queue(id),
    attempted_at  TEXT NOT NULL DEFAULT (datetime('now')),
    company_url   TEXT,
    candidates    TEXT,
    success       INTEGER
);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(queue)")}
        if "digest_job_links" not in existing_cols:
            conn.execute("ALTER TABLE queue ADD COLUMN digest_job_links TEXT")


def insert_queue_row(conn: sqlite3.Connection, row: dict) -> Optional[int]:
    """Insert a parsed Naukri email into the queue. Returns new row id, or None if it already existed."""
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO queue (
            gmail_message_id, gmail_thread_id, received_at, subject,
            company, role, job_link, digest_job_links, hr_email, hr_email_source,
            hr_email_confidence, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row["gmail_message_id"],
            row.get("gmail_thread_id"),
            row["received_at"],
            row.get("subject"),
            row.get("company"),
            row.get("role"),
            row.get("job_link"),
            json.dumps(row.get("digest_job_links", [])),
            row.get("hr_email"),
            row.get("hr_email_source", SOURCE_NONE),
            row.get("hr_email_confidence", "low"),
            row.get("status", STATUS_NEEDS_INFO),
        ),
    )
    return cur.lastrowid if cur.rowcount else None


def _deserialize(row: dict) -> dict:
    raw = row.get("digest_job_links")
    try:
        row["digest_job_links"] = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        row["digest_job_links"] = []
    return row


def list_queue(statuses: Optional[Iterable[str]] = None) -> list[dict]:
    with get_conn() as conn:
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            cur = conn.execute(
                f"SELECT * FROM queue WHERE status IN ({placeholders}) ORDER BY received_at DESC",
                tuple(statuses),
            )
        else:
            cur = conn.execute("SELECT * FROM queue ORDER BY received_at DESC")
        return [_deserialize(dict(r)) for r in cur.fetchall()]


def get_queue_row(row_id: int) -> Optional[dict]:
    with get_conn() as conn:
        cur = conn.execute("SELECT * FROM queue WHERE id = ?", (row_id,))
        r = cur.fetchone()
        return _deserialize(dict(r)) if r else None


def update_queue_row(row_id: int, fields: dict[str, Any]) -> None:
    if not fields:
        return
    fields = dict(fields)
    fields["updated_at"] = "CURRENT_TIMESTAMP_PLACEHOLDER"
    set_clause = ", ".join(f"{k} = ?" for k in fields if k != "updated_at")
    set_clause += ", updated_at = datetime('now')"
    values = [v for k, v in fields.items() if k != "updated_at"]
    values.append(row_id)
    with get_conn() as conn:
        conn.execute(f"UPDATE queue SET {set_clause} WHERE id = ?", values)


def record_scrape_attempt(queue_id: int, company_url: Optional[str], candidates: list[str], success: bool) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO scrape_attempts (queue_id, company_url, candidates, success) VALUES (?, ?, ?, ?)",
            (queue_id, company_url, json.dumps(candidates), 1 if success else 0),
        )
