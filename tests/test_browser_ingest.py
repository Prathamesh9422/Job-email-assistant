from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine, text

import browser_ingest
import db
from config import QUEUE_SOURCE_GMAIL, QUEUE_SOURCE_NAUKRI_PLUGIN, STATUS_NEEDS_INFO


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", future=True)
    monkeypatch.setattr(db, "_engine", engine)
    db.init_db()
    with db.get_conn() as conn:
        conn.execute(
            text(
                "INSERT INTO users (email, google_sub, refresh_token_encrypted, is_active, created_at, updated_at) "
                "VALUES ('a@b.com', 'sub1', 'x', 1, '2026-01-01', '2026-01-01')"
            )
        )
        conn.commit()
    yield 1  # user_id


def _job(**overrides):
    job = {
        "company": "Regami Solutions",
        "role": "React Js Developer -PET(Freshers)",
        "applied_date": "2026-08-26",
        "job_link": "https://naukri.com/job/123",
    }
    job.update(overrides)
    return job


def test_inserts_new_scraped_row(temp_db):
    user_id = temp_db
    result = browser_ingest.ingest_scraped_jobs(user_id, [_job()])

    assert result == {"received": 1, "inserted": 1, "skipped": 0, "errors": []}

    rows = db.list_queue(user_id, statuses=[STATUS_NEEDS_INFO])
    assert len(rows) == 1
    assert rows[0]["company"] == "Regami Solutions"
    assert rows[0]["source"] == QUEUE_SOURCE_NAUKRI_PLUGIN
    assert rows[0]["status"] == STATUS_NEEDS_INFO
    assert rows[0]["hr_email_source"] == "none"
    assert rows[0]["gmail_message_id"] is None


def test_duplicate_scrape_is_skipped_and_never_overwrites(temp_db):
    user_id = temp_db
    browser_ingest.ingest_scraped_jobs(user_id, [_job()])

    # Re-scrape the same job, this time with a (hypothetically) different
    # job_link - the existing row must not be touched.
    result = browser_ingest.ingest_scraped_jobs(user_id, [_job(job_link="https://naukri.com/different-link")])

    assert result == {"received": 1, "inserted": 0, "skipped": 1, "errors": []}
    rows = db.list_queue(user_id, statuses=[STATUS_NEEDS_INFO])
    assert len(rows) == 1
    assert rows[0]["job_link"] == "https://naukri.com/job/123"


def test_same_role_different_applied_date_is_a_new_row(temp_db):
    user_id = temp_db
    browser_ingest.ingest_scraped_jobs(user_id, [_job(applied_date="2026-08-26")])
    result = browser_ingest.ingest_scraped_jobs(user_id, [_job(applied_date="2026-08-27")])

    assert result["inserted"] == 1
    rows = db.list_queue(user_id, statuses=[STATUS_NEEDS_INFO])
    assert len(rows) == 2


def test_dedup_is_case_and_whitespace_insensitive(temp_db):
    user_id = temp_db
    browser_ingest.ingest_scraped_jobs(user_id, [_job(company="Regami Solutions")])
    result = browser_ingest.ingest_scraped_jobs(user_id, [_job(company="  regami solutions  ")])

    assert result["inserted"] == 0
    assert result["skipped"] == 1


def test_missing_required_field_is_skipped_with_error(temp_db):
    user_id = temp_db
    result = browser_ingest.ingest_scraped_jobs(user_id, [_job(company="")])

    assert result == {"received": 1, "inserted": 0, "skipped": 1, "errors": ["missing company"]}
    assert db.list_queue(user_id, statuses=[STATUS_NEEDS_INFO]) == []


def test_malformed_applied_date_is_skipped_with_error(temp_db):
    user_id = temp_db
    result = browser_ingest.ingest_scraped_jobs(user_id, [_job(applied_date="3 fortnights ago")])

    assert result["inserted"] == 0
    assert result["skipped"] == 1
    assert "applied_date" in result["errors"][0]


def test_missing_applied_date_is_skipped_with_error(temp_db):
    user_id = temp_db
    result = browser_ingest.ingest_scraped_jobs(user_id, [_job(applied_date="")])

    assert result == {"received": 1, "inserted": 0, "skipped": 1, "errors": ["missing applied_date"]}


def test_relative_date_text_is_accepted_end_to_end(temp_db):
    user_id = temp_db
    result = browser_ingest.ingest_scraped_jobs(user_id, [_job(applied_date="4 days ago")])

    assert result["inserted"] == 1
    rows = db.list_queue(user_id, statuses=[STATUS_NEEDS_INFO])
    expected = (date.today() - timedelta(days=4)).isoformat()
    assert rows[0]["applied_date"] == expected


def test_relative_and_equivalent_iso_date_dedup_against_each_other(temp_db):
    """A row scraped as "today" and later re-scraped with the resolved ISO
    date for that same day must be treated as the same application."""
    user_id = temp_db
    today_iso = date.today().isoformat()

    first = browser_ingest.ingest_scraped_jobs(user_id, [_job(applied_date="today")])
    second = browser_ingest.ingest_scraped_jobs(user_id, [_job(applied_date=today_iso)])

    assert first["inserted"] == 1
    assert second["inserted"] == 0
    assert second["skipped"] == 1


def test_batch_mixes_valid_invalid_and_duplicate(temp_db):
    user_id = temp_db
    browser_ingest.ingest_scraped_jobs(user_id, [_job(role="Existing Role")])

    result = browser_ingest.ingest_scraped_jobs(
        user_id,
        [
            _job(role="Existing Role"),  # duplicate -> skipped
            _job(role="New Role"),  # new -> inserted
            _job(role="Bad Row", applied_date="not-a-date"),  # invalid -> skipped
        ],
    )

    assert result["received"] == 3
    assert result["inserted"] == 1
    assert result["skipped"] == 2
    assert len(result["errors"]) == 1


def test_gmail_and_scraped_rows_coexist_without_dedup_key_collision(temp_db):
    user_id = temp_db
    with db.get_conn() as conn:
        row_id_1 = db.insert_queue_row(
            conn,
            user_id,
            {
                "gmail_message_id": "msg-1",
                "received_at": "2026-08-26T00:00:00+00:00",
                "company": "Some Co",
                "role": "Some Role",
            },
        )
        row_id_2 = db.insert_queue_row(
            conn,
            user_id,
            {
                "gmail_message_id": "msg-2",
                "received_at": "2026-08-27T00:00:00+00:00",
                "company": "Some Co",
                "role": "Some Role",
            },
        )
    assert row_id_1 is not None
    assert row_id_2 is not None  # two NULL dedup_keys don't collide with each other

    result = browser_ingest.ingest_scraped_jobs(user_id, [_job(company="Some Co", role="Some Role")])
    assert result["inserted"] == 1  # scraped row dedups independently of gmail rows

    rows = db.list_queue(user_id, statuses=[STATUS_NEEDS_INFO])
    sources = sorted(r["source"] for r in rows)
    assert sources == [QUEUE_SOURCE_GMAIL, QUEUE_SOURCE_GMAIL, QUEUE_SOURCE_NAUKRI_PLUGIN]


# --- resolve_applied_date: Naukri relative-date text -> YYYY-MM-DD ---

_FIXED_TODAY = date(2026, 8, 31)  # a Monday


@pytest.mark.parametrize(
    "text, expected",
    [
        ("today", "2026-08-31"),
        ("Today", "2026-08-31"),
        ("  today  ", "2026-08-31"),
        ("yesterday", "2026-08-30"),
        ("Yesterday", "2026-08-30"),
        ("0 days ago", "2026-08-31"),
        ("1 day ago", "2026-08-30"),
        ("2 days ago", "2026-08-29"),
        ("4 days ago", "2026-08-27"),
        ("4  days  ago", "2026-08-27"),
        ("1 week ago", "2026-08-24"),
        ("1 weeks ago", "2026-08-24"),
        ("2 weeks ago", "2026-08-17"),
        ("2026-08-15", "2026-08-15"),  # already-ISO passes through unchanged
    ],
)
def test_resolve_applied_date(text, expected):
    assert browser_ingest.resolve_applied_date(text, today=_FIXED_TODAY) == expected


@pytest.mark.parametrize(
    "text",
    ["", "sometime last month", "3 fortnights ago", "next week", "N/A", "1w ago"],
)
def test_resolve_applied_date_rejects_unrecognized_text(text):
    with pytest.raises(browser_ingest.ScrapedJobError):
        browser_ingest.resolve_applied_date(text, today=_FIXED_TODAY)


def test_resolve_applied_date_defaults_to_real_today_when_not_pinned():
    assert browser_ingest.resolve_applied_date("today") == date.today().isoformat()
