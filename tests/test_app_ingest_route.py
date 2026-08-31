import pytest
from sqlalchemy import create_engine
from starlette.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", future=True)
    import db

    monkeypatch.setattr(db, "_engine", engine)
    db.init_db()  # app's module-level init_db() only runs on first import (module cache) - redo it here per test

    import app
    import auth

    user = db.upsert_user("route@test.com", "sub-route", "fake-refresh-token")
    token = auth.generate_api_token(user["id"])
    with TestClient(app.app) as c:
        yield c, token, user["id"]


def test_ingest_scraped_requires_auth(client):
    c, _token, _user_id = client
    resp = c.post("/api/queue/ingest-scraped", json={"jobs": []})
    assert resp.status_code == 401


def test_ingest_scraped_rejects_bad_token(client):
    c, _token, _user_id = client
    resp = c.post(
        "/api/queue/ingest-scraped",
        json={"jobs": []},
        headers={"Authorization": "Bearer not-the-real-token"},
    )
    assert resp.status_code == 401


def test_ingest_scraped_accepts_valid_bearer_token(client):
    c, token, _user_id = client
    resp = c.post(
        "/api/queue/ingest-scraped",
        json={"jobs": [{"company": "Acme", "role": "Engineer", "applied_date": "today"}]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["inserted"] == 1


def test_null_applied_date_is_a_per_row_skip_not_a_batch_rejection(client):
    """A scraped job with no relative-date text (e.g. an external-site
    posting) has applied_date=None. That one row must be skipped with an
    error - it must not 422 the entire batch before browser_ingest.py's
    per-row validation even runs."""
    c, token, _user_id = client
    resp = c.post(
        "/api/queue/ingest-scraped",
        json={
            "jobs": [
                {"company": "Good Co", "role": "Engineer", "applied_date": "today"},
                {"company": "Bad Co", "role": "No Date Role", "applied_date": None},
            ]
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["received"] == 2
    assert body["inserted"] == 1
    assert body["skipped"] == 1
    assert "missing applied_date" in body["errors"][0]


def test_generate_api_token_requires_session_not_bearer_token(client):
    """The token-generation endpoint must stay session-only - a valid API
    token must not be able to mint another token for itself."""
    c, token, _user_id = client
    resp = c.post("/api/settings/api-token", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
