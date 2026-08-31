import pytest
from sqlalchemy import create_engine

import auth
import db


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", future=True)
    monkeypatch.setattr(db, "_engine", engine)
    db.init_db()
    user = db.upsert_user("ext@test.com", "sub-ext", "fake-refresh-token")
    yield user["id"]


def test_generate_api_token_roundtrip(temp_db):
    user_id = temp_db
    token = auth.generate_api_token(user_id)

    assert token
    resolved = db.get_user_by_api_token_hash(auth._hash_api_token(token))
    assert resolved is not None
    assert resolved["id"] == user_id


def test_wrong_token_resolves_to_nobody(temp_db):
    user_id = temp_db
    auth.generate_api_token(user_id)

    assert db.get_user_by_api_token_hash(auth._hash_api_token("not-the-real-token")) is None


def test_regenerating_invalidates_the_old_token(temp_db):
    user_id = temp_db
    old_token = auth.generate_api_token(user_id)
    new_token = auth.generate_api_token(user_id)

    assert old_token != new_token
    assert db.get_user_by_api_token_hash(auth._hash_api_token(old_token)) is None
    resolved = db.get_user_by_api_token_hash(auth._hash_api_token(new_token))
    assert resolved is not None
    assert resolved["id"] == user_id


def test_plaintext_token_is_never_stored(temp_db):
    user_id = temp_db
    token = auth.generate_api_token(user_id)

    user = db.get_user(user_id)
    assert token not in str(user)  # only the hash lives in the row
