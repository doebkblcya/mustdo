from __future__ import annotations

import os
import sys
import tempfile
import unittest

from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.config import get_settings  # noqa: E402
from app.db import get_connection, init_db  # noqa: E402
from app.time_utils import utcish_now_iso  # noqa: E402


def _create_admin(username: str, password_hash: str) -> int:
    with get_connection() as db:
        cur = db.execute(
            """
            INSERT INTO admins
                (username, username_normalized, password_hash, session_version,
                 status, created_at, updated_at)
            VALUES (?, ?, ?, 1, 'active', ?, ?)
            """,
            (username, username.lower(), password_hash, utcish_now_iso(), utcish_now_iso()),
        )
        db.commit()
        return int(cur.lastrowid)


class AdminAuthTests(unittest.TestCase):
    """End-to-end login/session lifecycle through the app's TestClient."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.env = patch.dict(
            os.environ,
            {
                "DATABASE_PATH": os.path.join(self.tmpdir.name, "test.db"),
                "SECRET_KEY": "test-secret",
            },
            clear=False,
        )
        self.env.start()
        get_settings.cache_clear()
        init_db()

    def tearDown(self) -> None:
        self.env.stop()
        self.tmpdir.cleanup()
        get_settings.cache_clear()

    def _client(self):
        from starlette.testclient import TestClient

        from app.main import app

        return TestClient(app, raise_server_exceptions=False)

    def test_login_success_sets_session(self) -> None:
        from app.admin_security import hash_password

        _create_admin("admin", hash_password("correct-password-1"))
        c = self._client()
        r = c.post(
            "/admin/login",
            data={"username": "admin", "password": "correct-password-1"},
            follow_redirects=False,
        )
        self.assertEqual(r.status_code, 302)
        self.assertIn("session", r.headers.get("set-cookie", ""))
        # An authenticated request to a list view succeeds.
        r = c.get("/admin/user/list", follow_redirects=False)
        self.assertEqual(r.status_code, 200)

    def test_login_wrong_password_rejected(self) -> None:
        from app.admin_security import hash_password

        _create_admin("admin", hash_password("correct-password-1"))
        c = self._client()
        r = c.post(
            "/admin/login",
            data={"username": "admin", "password": "wrong"},
            follow_redirects=False,
        )
        # Username/password mismatch -> login fails -> redirect back to login.
        self.assertNotEqual(r.status_code, 200)
        # Not authenticated: list view redirects away.
        r = c.get("/admin/user/list", follow_redirects=False)
        self.assertIn(r.status_code, (302, 307))

    def test_disabled_admin_session_invalidated(self) -> None:
        from app.admin_security import hash_password

        admin_id = _create_admin("admin", hash_password("correct-password-1"))
        c = self._client()
        c.post(
            "/admin/login",
            data={"username": "admin", "password": "correct-password-1"},
            follow_redirects=False,
        )
        # Authenticated now.
        self.assertEqual(c.get("/admin/user/list", follow_redirects=False).status_code, 200)

        # Disable the admin AND bump session_version (as the disable flow does).
        with get_connection() as db:
            db.execute(
                "UPDATE admins SET status = 'disabled', session_version = session_version + 1 WHERE id = ?",
                (admin_id,),
            )
            db.commit()

        # Old session must now be rejected.
        self.assertIn(c.get("/admin/user/list", follow_redirects=False).status_code, (302, 307))

    def test_password_change_invalidates_session(self) -> None:
        from app.admin_security import hash_password

        admin_id = _create_admin("admin", hash_password("old-password-1"))
        c = self._client()
        c.post(
            "/admin/login",
            data={"username": "admin", "password": "old-password-1"},
            follow_redirects=False,
        )
        self.assertEqual(c.get("/admin/user/list", follow_redirects=False).status_code, 200)

        # Change password -> session_version bump (what create_admin does).
        with get_connection() as db:
            db.execute(
                "UPDATE admins SET password_hash = ?, session_version = session_version + 1 WHERE id = ?",
                (hash_password("new-password-1"), admin_id),
            )
            db.commit()

        self.assertIn(c.get("/admin/user/list", follow_redirects=False).status_code, (302, 307))


if __name__ == "__main__":
    unittest.main()
