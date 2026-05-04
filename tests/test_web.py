import asyncio
import os
import tempfile

from fastapi.testclient import TestClient

from aprs_tak_gateway import web
from aprs_tak_gateway.roster import RosterDB


def test_login_sets_session_cookie_used_by_authenticated_routes():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "roster.db")
        db = RosterDB(db_path)
        asyncio.run(db.initialize())
        asyncio.run(db.set_setting("web_admin_password_hash", web._hash_password("secret")))

        original_db = web.roster_db
        original_config = web.config
        original_secret = web.secret_key_value
        web.roster_db = db
        web.config = {"web": {"secret_key": "test-secret"}, "database": {"path": db_path}}
        web.secret_key_value = None

        try:
            client = TestClient(web.app)
            response = client.post("/login", data={"password": "secret"}, follow_redirects=True)

            assert response.status_code == 200
            assert "Roster" in response.text
            assert str(response.url).endswith("/")
            assert web.SESSION_COOKIE in client.cookies
        finally:
            web.roster_db = original_db
            web.config = original_config
            web.secret_key_value = original_secret
            asyncio.run(db.close())


def test_secret_key_requires_explicit_configuration():
    original_config = web.config
    original_secret = web.secret_key_value
    web.config = {"web": {}, "database": {"path": ":memory:"}}
    web.secret_key_value = None

    try:
        try:
            web._get_secret_key()
        except RuntimeError as exc:
            assert "web.secret_key" in str(exc)
        else:
            raise AssertionError("Expected missing secret key to fail")
    finally:
        web.config = original_config
        web.secret_key_value = original_secret
