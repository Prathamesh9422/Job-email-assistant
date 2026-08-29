"""Database access layer for the triage queue.

Backed by SQLAlchemy Core so the exact same code works against local SQLite
(default, no setup needed) or Railway's managed Postgres in production
(DATABASE_URL env var). Every public function here keeps the same name,
signature, and return shape regardless of backend, so callers (app.py,
fetch_job.py, naukri_parser.py) never need to know or care which one is active.
"""
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from config import DATABASE_URL, SOURCE_NONE, STATUS_NEEDS_INFO

_engine: Optional[Engine] = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(DATABASE_URL, future=True)
    return _engine


def _is_postgres() -> bool:
    return get_engine().dialect.name == "postgresql"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_conn():
    conn = get_engine().connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _postgres_schema() -> list[str]:
    return [
        """
        CREATE TABLE IF NOT EXISTS queue (
            id                  BIGSERIAL PRIMARY KEY,
            gmail_message_id    TEXT UNIQUE NOT NULL,
            gmail_thread_id     TEXT,
            received_at         TEXT NOT NULL,
            subject             TEXT,
            company             TEXT,
            role                TEXT,
            job_link            TEXT,
            digest_job_links    TEXT,
            hr_email            TEXT,
            hr_name             TEXT,
            hr_email_source     TEXT NOT NULL DEFAULT 'none',
            hr_email_confidence TEXT NOT NULL DEFAULT 'low',
            template_used       TEXT,
            final_subject       TEXT,
            final_body          TEXT,
            status              TEXT NOT NULL DEFAULT 'needs_info',
            error_message       TEXT,
            resume_filename     TEXT,
            sent_at             TEXT,
            created_at          TEXT NOT NULL,
            updated_at          TEXT NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_queue_status ON queue(status)",
        """
        CREATE TABLE IF NOT EXISTS scrape_attempts (
            id            BIGSERIAL PRIMARY KEY,
            queue_id      BIGINT NOT NULL REFERENCES queue(id),
            attempted_at  TEXT NOT NULL,
            company_url   TEXT,
            candidates    TEXT,
            success       INTEGER
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS scheduler_state (
            id                 BIGSERIAL PRIMARY KEY,
            run_started_at     TEXT NOT NULL,
            run_finished_at    TEXT,
            status             TEXT NOT NULL,
            error_message      TEXT,
            messages_found     INTEGER,
            rows_inserted      INTEGER,
            last_checked_date  TEXT
        )
        """,
        # Defensive top-up in case an older/partial table already exists.
        "ALTER TABLE queue ADD COLUMN IF NOT EXISTS digest_job_links TEXT",
        "ALTER TABLE queue ADD COLUMN IF NOT EXISTS final_subject TEXT",
        "ALTER TABLE queue ADD COLUMN IF NOT EXISTS final_body TEXT",
        "ALTER TABLE queue ADD COLUMN IF NOT EXISTS hr_name TEXT",
    ]


def _sqlite_schema() -> list[str]:
    return [
        """
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
            hr_name             TEXT,
            hr_email_source     TEXT NOT NULL DEFAULT 'none',
            hr_email_confidence TEXT NOT NULL DEFAULT 'low',
            template_used       TEXT,
            final_subject       TEXT,
            final_body          TEXT,
            status              TEXT NOT NULL DEFAULT 'needs_info',
            error_message       TEXT,
            resume_filename     TEXT,
            sent_at             TEXT,
            created_at          TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_queue_status ON queue(status)",
        """
        CREATE TABLE IF NOT EXISTS scrape_attempts (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            queue_id      INTEGER NOT NULL REFERENCES queue(id),
            attempted_at  TEXT NOT NULL DEFAULT (datetime('now')),
            company_url   TEXT,
            candidates    TEXT,
            success       INTEGER
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS scheduler_state (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            run_started_at     TEXT NOT NULL,
            run_finished_at    TEXT,
            status             TEXT NOT NULL,
            error_message      TEXT,
            messages_found     INTEGER,
            rows_inserted      INTEGER,
            last_checked_date  TEXT
        )
        """,
    ]


def init_db() -> None:
    with get_conn() as conn:
        if _is_postgres():
            for stmt in _postgres_schema():
                conn.execute(text(stmt))
            return

        for stmt in _sqlite_schema():
            conn.execute(text(stmt))

        existing_cols = {
            row[1] for row in conn.execute(text("PRAGMA table_info(queue)"))
        }
        for col in ("digest_job_links", "final_subject", "final_body", "hr_name"):
            if col not in existing_cols:
                conn.execute(text(f"ALTER TABLE queue ADD COLUMN {col} TEXT"))


def insert_queue_row(conn, row: dict) -> Optional[int]:
    """Insert a parsed Naukri email into the queue. Returns new row id, or None if it already existed."""
    ts = _now()
    params = {
        "gmail_message_id": row["gmail_message_id"],
        "gmail_thread_id": row.get("gmail_thread_id"),
        "received_at": row["received_at"],
        "subject": row.get("subject"),
        "company": row.get("company"),
        "role": row.get("role"),
        "job_link": row.get("job_link"),
        "digest_job_links": json.dumps(row.get("digest_job_links", [])),
        "hr_email": row.get("hr_email"),
        "hr_name": row.get("hr_name"),
        "hr_email_source": row.get("hr_email_source", SOURCE_NONE),
        "hr_email_confidence": row.get("hr_email_confidence", "low"),
        "status": row.get("status", STATUS_NEEDS_INFO),
        "created_at": ts,
        "updated_at": ts,
    }
    cols = ", ".join(params.keys())
    placeholders = ", ".join(f":{k}" for k in params.keys())

    if _is_postgres():
        sql = (
            f"INSERT INTO queue ({cols}) VALUES ({placeholders}) "
            "ON CONFLICT (gmail_message_id) DO NOTHING RETURNING id"
        )
        result = conn.execute(text(sql), params)
        conn.commit()
        row_result = result.fetchone()
        return row_result[0] if row_result else None

    sql = f"INSERT OR IGNORE INTO queue ({cols}) VALUES ({placeholders})"
    result = conn.execute(text(sql), params)
    conn.commit()
    return result.lastrowid if result.rowcount else None


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
            statuses = list(statuses)
            params = {f"s{i}": s for i, s in enumerate(statuses)}
            placeholders = ", ".join(f":{k}" for k in params)
            result = conn.execute(
                text(f"SELECT * FROM queue WHERE status IN ({placeholders}) ORDER BY received_at DESC"),
                params,
            )
        else:
            result = conn.execute(text("SELECT * FROM queue ORDER BY received_at DESC"))
        return [_deserialize(dict(r._mapping)) for r in result]


def get_queue_row(row_id: int) -> Optional[dict]:
    with get_conn() as conn:
        result = conn.execute(text("SELECT * FROM queue WHERE id = :id"), {"id": row_id})
        r = result.fetchone()
        return _deserialize(dict(r._mapping)) if r else None


def update_queue_row(row_id: int, fields: dict[str, Any]) -> None:
    if not fields:
        return
    fields = dict(fields)
    fields["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    params = dict(fields)
    params["id"] = row_id
    with get_conn() as conn:
        conn.execute(text(f"UPDATE queue SET {set_clause} WHERE id = :id"), params)


def record_scrape_attempt(queue_id: int, company_url: Optional[str], candidates: list[str], success: bool) -> None:
    with get_conn() as conn:
        conn.execute(
            text(
                "INSERT INTO scrape_attempts (queue_id, attempted_at, company_url, candidates, success) "
                "VALUES (:queue_id, :attempted_at, :company_url, :candidates, :success)"
            ),
            {
                "queue_id": queue_id,
                "attempted_at": _now(),
                "company_url": company_url,
                "candidates": json.dumps(candidates),
                "success": 1 if success else 0,
            },
        )


# --- Scheduler run tracking (replaces the old local state.json) ---


def get_last_checked() -> Optional[str]:
    """Returns the last_checked_date from the most recent successful run, or None."""
    with get_conn() as conn:
        result = conn.execute(
            text(
                "SELECT last_checked_date FROM scheduler_state "
                "WHERE status = 'success' AND last_checked_date IS NOT NULL "
                "ORDER BY run_started_at DESC LIMIT 1"
            )
        )
        row = result.fetchone()
        return row[0] if row else None


def start_run() -> int:
    """Records the start of a fetch run. Returns the new run's id."""
    ts = _now()
    with get_conn() as conn:
        if _is_postgres():
            result = conn.execute(
                text("INSERT INTO scheduler_state (run_started_at, status) VALUES (:ts, 'running') RETURNING id"),
                {"ts": ts},
            )
            conn.commit()
            return result.fetchone()[0]

        result = conn.execute(
            text("INSERT INTO scheduler_state (run_started_at, status) VALUES (:ts, 'running')"),
            {"ts": ts},
        )
        conn.commit()
        return result.lastrowid


def finish_run(
    run_id: int,
    status: str,
    error_message: Optional[str] = None,
    messages_found: int = 0,
    rows_inserted: int = 0,
    last_checked_date: Optional[str] = None,
) -> None:
    with get_conn() as conn:
        conn.execute(
            text(
                "UPDATE scheduler_state SET run_finished_at = :fin, status = :status, "
                "error_message = :err, messages_found = :mf, rows_inserted = :ri, "
                "last_checked_date = :lcd WHERE id = :id"
            ),
            {
                "fin": _now(),
                "status": status,
                "err": error_message,
                "mf": messages_found,
                "ri": rows_inserted,
                "lcd": last_checked_date,
                "id": run_id,
            },
        )


def get_latest_run() -> Optional[dict]:
    with get_conn() as conn:
        result = conn.execute(text("SELECT * FROM scheduler_state ORDER BY run_started_at DESC LIMIT 1"))
        row = result.fetchone()
        return dict(row._mapping) if row else None
