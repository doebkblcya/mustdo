from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import get_connection, init_db  # noqa: E402
from app.security import hash_session_token  # noqa: E402
from app.time_utils import now_shanghai, today_date, utcish_now_iso  # noqa: E402

TOKEN = "test-token-reminder"

# 注意：不要在此处模块级 `from app.main import app`。
# create_app() 会在导入期固化 admin 中间件的 admin_cookie_secure 与 SQLAdmin
# 引擎 URL（读取当时的环境变量）；模块级导入会抢在测试 setUp 的 env patch
# 之前执行，破坏 test_admin_auth 等先运行的用例。因此 app 在 setUp 中延迟导入。


class ReminderApiTests(unittest.TestCase):
    """HTTP 层端到端验证：路由注册、认证、校验、响应模型。"""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.env = patch.dict(
            os.environ,
            {
                "DATABASE_PATH": os.path.join(self.tmpdir.name, "test.db"),
                "SECRET_KEY": "test-secret",
                "WECHAT_TEMPLATE_ID": "HWgp5u4Z_E3QD_vFMzHEZ3_gL0PDdsbtA5i7vjWQ9jc",
            },
            clear=False,
        )
        self.env.start()
        get_settings.cache_clear()
        init_db()
        from app.main import app  # noqa: PLC0415 —— 延迟导入，见模块顶部说明

        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.env.stop()
        self.tmpdir.cleanup()
        get_settings.cache_clear()

    def _seed_user_with_session(self, openid: str = "openid-api") -> int:
        now = now_shanghai()
        now_iso = now.isoformat(timespec="seconds")
        db = get_connection()
        try:
            cursor = db.execute(
                """
                INSERT INTO users (wechat_openid, status, invite_redeemed_at, created_at, updated_at)
                VALUES (?, 'active', ?, ?, ?)
                """,
                (openid, now_iso, now_iso, now_iso),
            )
            user_id = int(cursor.lastrowid)
            db.execute(
                """
                INSERT INTO sessions (user_id, token_hash, created_at, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    user_id,
                    hash_session_token(TOKEN),
                    now_iso,
                    (now + timedelta(days=30)).isoformat(timespec="seconds"),
                ),
            )
            db.commit()
            return user_id
        finally:
            db.close()

    def _seed_todo(self, user_id: int, due_time: str | None = "14:30") -> int:
        now = utcish_now_iso()
        db = get_connection()
        try:
            cursor = db.execute(
                """
                INSERT INTO todos (user_id, content, due_date, due_time, status, created_at, updated_at)
                VALUES (?, 'API 待办', ?, ?, 'pending', ?, ?)
                """,
                (user_id, today_date().isoformat(), due_time, now, now),
            )
            db.commit()
            return int(cursor.lastrowid)
        finally:
            db.close()

    def _auth(self) -> dict[str, str]:
        return {"Authorization": "Bearer " + TOKEN}

    # ---------- tests ----------

    def test_put_requires_auth(self) -> None:
        resp = self.client.put("/api/todos/1/reminder", json={"remind_at": "2099-08-25T14:30:00+08:00"})
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["code"], "unauthorized")

    def test_put_creates_reminder(self) -> None:
        user_id = self._seed_user_with_session()
        todo_id = self._seed_todo(user_id)
        resp = self.client.put(
            f"/api/todos/{todo_id}/reminder",
            json={"remind_at": "2099-08-25T14:30:00+08:00"},
            headers=self._auth(),
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["reminder"]["status"], "pending")
        self.assertEqual(body["reminder"]["remind_at"], "2099-08-25T14:30:00+08:00")

    def test_put_requires_due_time(self) -> None:
        user_id = self._seed_user_with_session()
        todo_id = self._seed_todo(user_id, due_time=None)
        resp = self.client.put(
            f"/api/todos/{todo_id}/reminder",
            json={"remind_at": "2099-08-25T14:30:00+08:00"},
            headers=self._auth(),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["code"], "reminder_requires_time")

    def test_put_rejects_past(self) -> None:
        user_id = self._seed_user_with_session()
        todo_id = self._seed_todo(user_id)
        resp = self.client.put(
            f"/api/todos/{todo_id}/reminder",
            json={"remind_at": "2020-01-01T00:00:00+08:00"},
            headers=self._auth(),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["code"], "reminder_time_in_past")

    def test_put_rejects_bad_format_422(self) -> None:
        user_id = self._seed_user_with_session()
        todo_id = self._seed_todo(user_id)
        resp = self.client.put(
            f"/api/todos/{todo_id}/reminder",
            json={"remind_at": "not-a-date"},
            headers=self._auth(),
        )
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.json()["code"], "validation_error")

    def test_put_rejects_foreign_todo(self) -> None:
        user_id = self._seed_user_with_session("openid-api")
        self._seed_todo(user_id)
        # 另一个用户（无 session，无邀请码）：其待办对当前 token 不可见
        now = now_shanghai().isoformat(timespec="seconds")
        db = get_connection()
        try:
            cursor = db.execute(
                """
                INSERT INTO users (wechat_openid, status, created_at, updated_at)
                VALUES ('openid-other', 'active', ?, ?)
                """,
                (now, now),
            )
            other_user_id = int(cursor.lastrowid)
            db.commit()
        finally:
            db.close()
        other_todo_id = self._seed_todo(other_user_id)
        resp = self.client.put(
            f"/api/todos/{other_todo_id}/reminder",
            json={"remind_at": "2099-08-25T14:30:00+08:00"},
            headers=self._auth(),
        )
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["code"], "todo_not_found")

    def test_list_includes_reminder_and_delete_clears_it(self) -> None:
        user_id = self._seed_user_with_session()
        todo_id = self._seed_todo(user_id)
        self.client.put(
            f"/api/todos/{todo_id}/reminder",
            json={"remind_at": "2099-08-25T14:30:00+08:00"},
            headers=self._auth(),
        )
        listed = self.client.get("/api/todos", headers=self._auth()).json()
        todo = next(t for t in listed["groups"]["today"] if t["id"] == todo_id)
        self.assertIsNotNone(todo["reminder"])
        self.assertEqual(todo["reminder"]["status"], "pending")

        resp = self.client.delete(f"/api/todos/{todo_id}/reminder", headers=self._auth())
        self.assertEqual(resp.status_code, 204)
        listed2 = self.client.get("/api/todos", headers=self._auth()).json()
        todo2 = next(t for t in listed2["groups"]["today"] if t["id"] == todo_id)
        self.assertIsNone(todo2["reminder"])
        db = get_connection()
        try:
            status = db.execute(
                "SELECT status FROM todo_reminders WHERE todo_id = ?", (todo_id,)
            ).fetchone()["status"]
        finally:
            db.close()
        self.assertEqual(status, "cancelled")

    def test_patch_done_through_http_cancels_reminder(self) -> None:
        user_id = self._seed_user_with_session()
        todo_id = self._seed_todo(user_id)
        self.client.put(
            f"/api/todos/{todo_id}/reminder",
            json={"remind_at": "2099-08-25T14:30:00+08:00"},
            headers=self._auth(),
        )
        patched = self.client.patch(
            f"/api/todos/{todo_id}",
            json={"status": "done"},
            headers=self._auth(),
        )
        self.assertEqual(patched.status_code, 200)
        self.assertIsNone(patched.json()["reminder"])


if __name__ == "__main__":
    unittest.main()
