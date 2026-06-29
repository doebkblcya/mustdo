from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from starlette.responses import Response


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.config import get_settings  # noqa: E402
from app.db import get_connection, init_db  # noqa: E402
from app.deps import current_user  # noqa: E402
from app.routers.auth import login_for_token, logout  # noqa: E402
from app.schemas import LoginRequest  # noqa: E402
from app.security import hash_password, normalize_username  # noqa: E402
from app.time_utils import now_shanghai  # noqa: E402


class BearerAuthTests(unittest.TestCase):
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

    def _create_user(self, username: str = "tester", password: str = "password123") -> int:
        now = now_shanghai().isoformat(timespec="seconds")
        db = get_connection()
        try:
            cursor = db.execute(
                """
                INSERT INTO users (
                    username, username_normalized, password_hash, status, created_at, updated_at
                )
                VALUES (?, ?, ?, 'active', ?, ?)
                """,
                (username, normalize_username(username), hash_password(password), now, now),
            )
            db.commit()
            return int(cursor.lastrowid)
        finally:
            db.close()

    def test_token_login_returns_bearer_token(self) -> None:
        user_id = self._create_user()
        db = get_connection()
        try:
            result = login_for_token(LoginRequest(username="tester", password="password123"), db=db)
            session = db.execute("SELECT * FROM sessions WHERE user_id = ?", (user_id,)).fetchone()
        finally:
            db.close()

        self.assertEqual(result.user.id, user_id)
        self.assertEqual(result.token_type, "bearer")
        self.assertTrue(result.token)
        self.assertIsNotNone(session)

    def test_current_user_accepts_bearer_token(self) -> None:
        user_id = self._create_user()
        db = get_connection()
        try:
            token = login_for_token(LoginRequest(username="tester", password="password123"), db=db).token
            user = current_user(db=db, session_token=None, authorization=f"Bearer {token}")
        finally:
            db.close()

        self.assertEqual(user["id"], user_id)

    def test_logout_revokes_bearer_token(self) -> None:
        self._create_user()
        db = get_connection()
        try:
            token = login_for_token(LoginRequest(username="tester", password="password123"), db=db).token
            logout(Response(), db=db, session_token=None, authorization=f"Bearer {token}")
            with self.assertRaises(HTTPException) as raised:
                current_user(db=db, session_token=None, authorization=f"Bearer {token}")
        finally:
            db.close()

        self.assertEqual(raised.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
