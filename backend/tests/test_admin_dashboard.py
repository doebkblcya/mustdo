from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.admin_security import hash_password
from app.config import get_settings
from app.db import get_connection, init_db
from app.time_utils import utcish_now_iso


class AdminDashboardTests(unittest.TestCase):
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
        self.now = utcish_now_iso()
        self._seed()

    def tearDown(self) -> None:
        self.env.stop()
        self.tmpdir.cleanup()
        get_settings.cache_clear()

    def _seed(self) -> None:
        with get_connection() as db:
            db.execute(
                """
                INSERT INTO admins
                    (username, username_normalized, password_hash, session_version,
                     status, created_at, updated_at)
                VALUES ('admin', 'admin', ?, 1, 'active', ?, ?)
                """,
                (hash_password("correct-password-1"), self.now, self.now),
            )
            db.execute(
                """
                INSERT INTO users
                    (wechat_openid, status, invite_redeemed_at, created_at, updated_at, last_login_at)
                VALUES ('openid-dashboard-user', 'active', ?, ?, ?, ?)
                """,
                (self.now, self.now, self.now, self.now),
            )
            db.execute(
                """
                INSERT INTO user_quotas
                    (user_id, asr_enabled, asr_daily_seconds, ai_enabled,
                     ai_daily_tokens, created_at, updated_at)
                VALUES (1, 1, 100, 1, 1000, ?, ?)
                """,
                (self.now, self.now),
            )
            db.execute(
                """
                INSERT INTO asr_usage
                    (user_id, request_id, audio_seconds, status, duration_ms, created_at)
                VALUES (1, 'req-1', 85, 'success', 420, ?)
                """,
                (self.now,),
            )
            db.execute(
                """
                INSERT INTO ai_usage
                    (user_id, purpose, status, prompt_tokens, completion_tokens,
                     total_tokens, cache_hit_tokens, cache_miss_tokens, duration_ms, created_at)
                VALUES (1, 'parse', 'success', 600, 300, 900, 0, 0, 650, ?)
                """,
                (self.now,),
            )
            todo = db.execute(
                """
                INSERT INTO todos
                    (user_id, content, due_date, due_time, status, pinned, created_at, updated_at)
                VALUES (1, '测试提醒待办', '2099-01-01', '12:00', 'pending', 0, ?, ?)
                """,
                (self.now, self.now),
            )
            db.execute(
                """
                INSERT INTO todo_reminders
                    (todo_id, user_id, remind_at, status, created_at, error_code, updated_at)
                VALUES (?, 1, '2099-01-01T11:30:00+08:00', 'failed', ?, '43101', ?)
                """,
                (todo.lastrowid, self.now, self.now),
            )
            db.commit()

    def _client(self):
        from starlette.testclient import TestClient

        from app.main import create_app

        return TestClient(create_app(), raise_server_exceptions=False)

    def _login(self, client) -> None:
        response = client.post(
            "/admin/login",
            data={"username": "admin", "password": "correct-password-1"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

    def test_dashboard_service_aggregates_and_flags_quota(self) -> None:
        from app.services.admin_dashboard import collect_dashboard

        with get_connection() as db:
            result = collect_dashboard(db, 7)
        self.assertEqual(result["users"]["active"], 1)
        self.assertEqual(result["asr"]["calls"], 1)
        self.assertEqual(result["ai"]["tokens"], 900)
        self.assertEqual(result["reminders"]["failed"], 1)
        self.assertEqual(result["quota_alerts"][0]["user_id"], 1)
        self.assertEqual(len(result["trend"]), 7)

    def test_user_listing_filters_and_masks_identity(self) -> None:
        from app.services.admin_dashboard import list_users

        with get_connection() as db:
            result = list_users(db, query="dashboard", usage="near")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["asr_ratio"], 85)
        self.assertEqual(result["items"][0]["openid_masked"], "openi…user")

    def test_custom_pages_require_login(self) -> None:
        client = self._client()
        for url in (
            "/admin/",
            "/admin/users",
            "/admin/users/1",
            "/admin/usage",
            "/admin/diagnostics",
        ):
            response = client.get(url, follow_redirects=False)
            self.assertIn(response.status_code, (302, 307), msg=url)

    def test_custom_pages_render_linked_data(self) -> None:
        client = self._client()
        self._login(client)
        checks = {
            "/admin/": "运营概览",
            "/admin/users": "openid-dashboard-user"[:5],
            "/admin/users/1": "测试提醒待办",
            "/admin/usage": "900",
            "/admin/diagnostics?status=failed": "用户拒绝接收消息",
            "/admin/diagnostics?kind=todos": "测试提醒待办",
        }
        for url, marker in checks.items():
            response = client.get(url, follow_redirects=False)
            self.assertEqual(response.status_code, 200, msg=url)
            self.assertIn(marker, response.text, msg=url)

    def test_admin_theme_asset_is_served(self) -> None:
        client = self._client()
        response = client.get("/admin-assets/admin.css")
        self.assertEqual(response.status_code, 200)
        self.assertIn("mustdo-sidebar", response.text)


if __name__ == "__main__":
    unittest.main()
