import pytest
from sqlalchemy import create_engine, text

import db


@pytest.fixture()
def old_schema_db(tmp_path, monkeypatch):
    """Simulates a pre-ARC-0004 database: queue.gmail_message_id is NOT
    NULL and none of the ARC-0004 columns exist yet."""
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}", future=True)
    with engine.connect() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE users (
                    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
                    email                    TEXT UNIQUE NOT NULL,
                    google_sub               TEXT UNIQUE NOT NULL,
                    refresh_token_encrypted  TEXT NOT NULL,
                    is_active                INTEGER NOT NULL DEFAULT 1,
                    created_at               TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at               TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE queue (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id             INTEGER REFERENCES users(id),
                    gmail_message_id    TEXT UNIQUE NOT NULL,
                    gmail_thread_id     TEXT,
                    received_at         TEXT NOT NULL,
                    subject             TEXT,
                    company             TEXT,
                    role                TEXT,
                    job_link            TEXT,
                    hr_email            TEXT,
                    hr_name             TEXT,
                    hr_email_source     TEXT NOT NULL DEFAULT 'none',
                    hr_email_confidence TEXT NOT NULL DEFAULT 'low',
                    status              TEXT NOT NULL DEFAULT 'needs_info',
                    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
        )
        conn.execute(
            text(
                "INSERT INTO users (id, email, google_sub, refresh_token_encrypted, created_at, updated_at) "
                "VALUES (1, 'a@b.com', 'sub1', 'x', '2026-01-01', '2026-01-01')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO queue (user_id, gmail_message_id, received_at, company, role, status) "
                "VALUES (1, 'msg-old-1', '2026-08-20T00:00:00+00:00', 'Old Co', 'Old Role', 'sent')"
            )
        )
        conn.execute(text("CREATE TABLE scrape_attempts (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
        conn.execute(text("CREATE TABLE scheduler_state (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
        conn.commit()

    monkeypatch.setattr(db, "_engine", engine)
    return engine


def test_init_db_migrates_old_schema_without_losing_data(old_schema_db):
    db.init_db()

    with db.get_conn() as conn:
        row = conn.execute(text("SELECT * FROM queue WHERE gmail_message_id = 'msg-old-1'")).fetchone()
        assert row is not None
        row = dict(row._mapping)
        assert row["company"] == "Old Co"
        assert row["status"] == "sent"
        assert row["source"] == "gmail"  # backfilled default for pre-existing rows

        info = {r[1]: r for r in conn.execute(text("PRAGMA table_info(queue)"))}
        assert info["gmail_message_id"][3] == 0  # notnull flag now off
        assert "dedup_key" in info
        assert "applied_date" in info


def test_init_db_migration_is_idempotent(old_schema_db):
    db.init_db()
    db.init_db()  # must not error or duplicate data on a second run

    with db.get_conn() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM queue")).fetchone()[0]
        assert count == 1


def test_scraped_insert_works_after_migrating_from_old_schema(old_schema_db):
    db.init_db()
    with db.get_conn() as conn:
        row_id = db.insert_scraped_row(
            conn,
            user_id=1,
            row={"company": "New Co", "role": "New Role", "applied_date": "2026-08-30"},
        )
    assert row_id is not None
    row = db.get_queue_row(1, row_id)
    assert row["gmail_message_id"] is None
    assert row["source"] == "naukri_plugin"
