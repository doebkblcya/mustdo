"""Admin console: per-user historical ASR/AI usage aggregation + page."""

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

OLD = "2020-01-01T10:00:00+08:00"


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


def _add_asr(user_id: int, seconds: float, created_at: str, status: str = "success") -> None:
    with get_connection() as db:
        db.execute(
            """
            INSERT INTO asr_usage
                (user_id, request_id, logid, audio_seconds, status, error_code, duration_ms, created_at)
            VALUES (?, ?, NULL, ?, ?, NULL, 120, ?)
            """,
            (user_id, f"req-{seconds}-{created_at}", seconds, status, created_at),
        )
        db.commit()


def _add_ai(user_id: int, purpose: str, tokens: int, created_at: str) -> None:
    with get_connection() as db:
        db.execute(
            """
            INSERT INTO ai_usage
                (user_id, purpose, status, prompt_tokens, completion_tokens, total_tokens,
                 cache_hit_tokens, cache_miss_tokens, error_code, duration_ms, created_at)
            VALUES (?, ?, 'success', 0, 0, ?, 0, 0, NULL, 200, ?)
            """,
            (user_id, purpose, tokens, created_at),
        )
        db.commit()


class UsageHistoryServiceTests(unittest.TestCase):
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

    def test_windows_and_aggregation(self) -> None:
        from app.services.usage_history import collect_user_usage

        uid = _create_user("openid-hist")
        now = utcish_now_iso()
        _add_asr(uid, 12.3, now)
        _add_asr(uid, 8.0, now)
        _add_asr(uid, 5.0, OLD)
        _add_ai(uid, "parse", 12400, now)
        _add_ai(uid, "organize", 600, now)

        with get_connection() as db:
            last7 = collect_user_usage(db, uid, 7)
            today = collect_user_usage(db, uid, 1)
            all_time = collect_user_usage(db, uid, 0)
            missing = collect_user_usage(db, uid + 999, 7)

        self.assertEqual(last7["openid"], "openid-hist")
        self.assertEqual(last7["asr"]["calls"], 2)          # 2020 row is outside 7 days
        self.assertAlmostEqual(last7["asr"]["seconds"], 20.3)
        self.assertEqual(last7["ai"][0]["total_tokens"] + last7["ai"][1]["total_tokens"], 13000)
        self.assertEqual(len(last7["per_day"]), 1)          # only today

        self.assertEqual(today["asr"]["calls"], 2)          # today only
        self.assertAlmostEqual(today["asr"]["seconds"], 20.3)
        self.assertEqual(today["since_label"], "今天")

        # days=0 -> all time, including the 2020 row.
        self.assertEqual(all_time["asr"]["calls"], 3)
        self.assertAlmostEqual(all_time["asr"]["seconds"], 25.3)
        self.assertEqual(all_time["since_label"], "全部")
        self.assertEqual(len(all_time["per_day"]), 2)       # old day + today

        self.assertIsNone(missing["openid"])
        self.assertIsNone(missing["asr"])


class UsageHistoryPageTests(unittest.TestCase):
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

    def test_page_requires_login(self) -> None:
        c = self._client()
        r = c.get("/admin/usage/user", follow_redirects=False)
        self.assertIn(r.status_code, (302, 307))

    def test_page_renders_aggregation(self) -> None:
        c = self._client()
        self._login(c)

        uid = _create_user("openid-page")
        now = utcish_now_iso()
        _add_asr(uid, 12.3, now)
        _add_asr(uid, 8.0, now)
        _add_ai(uid, "parse", 12400, now)

        r = c.get(f"/admin/usage/user?user_id={uid}&days=7", follow_redirects=False)
        self.assertEqual(r.status_code, 200)
        self.assertIn("openid-page", r.text)
        self.assertIn("20.3", r.text)          # ASR seconds aggregated
        self.assertIn("12,400", r.text)        # AI tokens formatted


if __name__ == "__main__":
    unittest.main()
