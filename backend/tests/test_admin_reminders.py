"""Admin console: read-only reminder ledger + today's reminder counts in the
usage summary."""

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


def _create_todo(user_id: int, content: str = "测试提醒", due_time: str = "14:30") -> int:
    now = utcish_now_iso()
    with get_connection() as db:
        cur = db.execute(
            """
            INSERT INTO todos (user_id, content, due_date, due_time, status, pinned, created_at, updated_at)
            VALUES (?, ?, '2099-08-25', ?, 'pending', 0, ?, ?)
            """,
            (user_id, content, due_time, now, now),
        )
        db.commit()
        return int(cur.lastrowid)


def _insert_reminder(todo_id: int, user_id: int, status: str,
                     error_code: str | None = None) -> None:
    now = utcish_now_iso()
    with get_connection() as db:
        db.execute(
            """
            INSERT INTO todo_reminders
                (todo_id, user_id, remind_at, status, created_at, sent_at, error_code, updated_at)
            VALUES (?, ?, '2099-08-25T14:30:00+08:00', ?, ?, ?, ?, ?)
            """,
            (todo_id, user_id, status, now,
             now if status == "sent" else None, error_code, now),
        )
        db.commit()


class AdminReminderTests(unittest.TestCase):
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

    def test_list_renders_status_user_todo_errcode(self) -> None:
        c = self._client()
        self._login(c)

        uid = _create_user("openid-reminder")
        todo_id = _create_todo(uid, "买牛奶")
        _insert_reminder(todo_id, uid, "failed", error_code="43101")

        r = c.get("/admin/todo-reminder/list", follow_redirects=False)
        self.assertEqual(r.status_code, 200)
        self.assertIn("买牛奶", r.text)      # todo content via relationship
        self.assertIn("openid-reminder", r.text)  # user openid via relationship
        self.assertIn("发送失败", r.text)    # status mapped to Chinese
        self.assertIn("43101", r.text)       # error_code column

    def test_list_requires_login(self) -> None:
        c = self._client()
        r = c.get("/admin/todo-reminder/list", follow_redirects=False)
        self.assertIn(r.status_code, (302, 307))

    def test_summary_counts_today_reminders(self) -> None:
        from app.services.quota import get_quota
        from app.services.summary import collect_usage_summary

        uid = _create_user("openid-summary")
        with get_connection() as db:
            get_quota(db, uid)

        # sent today, failed today, cancelled today (created today)
        _insert_reminder(_create_todo(uid, "a"), uid, "sent")
        _insert_reminder(_create_todo(uid, "b"), uid, "failed", error_code="47003")
        _insert_reminder(_create_todo(uid, "c"), uid, "cancelled")

        with get_connection() as db:
            rows = collect_usage_summary(db)
        row = next(r for r in rows if r["user_id"] == uid)
        self.assertEqual(row["reminder_created"], 3)
        self.assertEqual(row["reminder_sent"], 1)
        self.assertEqual(row["reminder_failed"], 1)


if __name__ == "__main__":
    unittest.main()
