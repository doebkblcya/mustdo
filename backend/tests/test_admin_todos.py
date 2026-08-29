"""Admin console: read-only todo view."""

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


def _create_user(openid: str) -> int:
    now = utcish_now_iso()
    with get_connection() as db:
        cur = db.execute(
            """
            INSERT INTO users (wechat_openid, status, created_at, updated_at, last_login_at)
            VALUES (?, 'active', ?, ?, ?)
            """,
            (openid, now, now, now),
        )
        db.commit()
        return int(cur.lastrowid)


def _create_todo(user_id: int, content: str, status: str = "pending") -> int:
    now = utcish_now_iso()
    with get_connection() as db:
        cur = db.execute(
            """
            INSERT INTO todos (user_id, content, due_date, due_time, status, pinned, created_at, updated_at)
            VALUES (?, ?, '2099-08-25', '14:30', ?, 0, ?, ?)
            """,
            (user_id, content, status, now, now),
        )
        db.commit()
        return int(cur.lastrowid)


class AdminTodoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.env = patch.dict(
            os.environ,
            {
                "DATABASE_PATH": os.path.join(self.tmpdir.name, "test.db"),
                "SECRET_KEY": "test-secret",
                "ADMIN_COOKIE_SECURE": "0",
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

        from app.main import create_app

        return TestClient(create_app(), raise_server_exceptions=False)

    def _login(self, c) -> None:
        from app.admin_security import hash_password

        _create_admin("admin", hash_password("correct-password-1"))
        r = c.post(
            "/admin/login",
            data={"username": "admin", "password": "correct-password-1"},
            follow_redirects=False,
        )
        self.assertEqual(r.status_code, 302)

    def test_list_requires_login(self) -> None:
        c = self._client()
        r = c.get("/admin/todo/list", follow_redirects=False)
        self.assertIn(r.status_code, (302, 307))

    def test_list_renders_user_content_status(self) -> None:
        c = self._client()
        self._login(c)

        uid = _create_user("openid-todo")
        _create_todo(uid, "买牛奶", status="pending")
        _create_todo(uid, "开会", status="done")

        r = c.get("/admin/todo/list", follow_redirects=False)
        self.assertEqual(r.status_code, 200)
        self.assertIn("买牛奶", r.text)
        self.assertIn("开会", r.text)
        self.assertIn("openid-todo", r.text)   # user openid via relationship
        self.assertIn("未完成", r.text)          # status formatter
        self.assertIn("已完成", r.text)


if __name__ == "__main__":
    unittest.main()
