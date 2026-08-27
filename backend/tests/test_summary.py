from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.config import get_settings
from app.db import get_connection, init_db
from app.services.quota import get_quota, record_ai_usage, record_asr_usage
from app.services.summary import collect_usage_summary
from app.time_utils import utcish_now_iso


class UsageSummaryTests(unittest.TestCase):
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
        self.db = get_connection()

    def tearDown(self) -> None:
        self.db.close()
        self.env.stop()
        self.tmpdir.cleanup()
        get_settings.cache_clear()

    def _add_user(self, openid: str) -> int:
        self.db.execute(
            "INSERT INTO users (wechat_openid, status, created_at, updated_at) VALUES (?,?,?,?)",
            (openid, "active", utcish_now_iso(), utcish_now_iso()),
        )
        self.db.commit()
        return int(
            self.db.execute(
                "SELECT id FROM users WHERE wechat_openid = ?", (openid,)
            ).fetchone()["id"]
        )

    def test_summary_groups_usage_and_reports_remaining(self) -> None:
        uid = self._add_user("openid_1")
        get_quota(self.db, uid)  # lazily creates an unlimited default row
        self.db.execute(
            "UPDATE user_quotas SET asr_daily_seconds = 600, ai_daily_tokens = 50000 WHERE user_id = ?",
            (uid,),
        )
        self.db.commit()

        record_asr_usage(
            self.db, uid, request_id="r1", logid="l1", audio_seconds=12.3,
            status="success", error_code=None, duration_ms=100,
        )
        record_asr_usage(
            self.db, uid, request_id="r2", logid="l2", audio_seconds=8.0,
            status="failed", error_code="asr_error", duration_ms=100,
        )
        record_ai_usage(
            self.db, uid, purpose="parse", status="success",
            prompt_tokens=0, completion_tokens=0, total_tokens=12400,
            cache_hit_tokens=0, cache_miss_tokens=0, error_code=None, duration_ms=200,
        )
        record_ai_usage(
            self.db, uid, purpose="organize", status="success",
            prompt_tokens=0, completion_tokens=0, total_tokens=600,
            cache_hit_tokens=0, cache_miss_tokens=0, error_code=None, duration_ms=200,
        )

        rows = collect_usage_summary(self.db)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["user_id"], uid)
        self.assertAlmostEqual(row["asr_used_seconds"], 20.3)
        self.assertEqual(row["asr_limit"], 600)
        self.assertEqual(row["asr_calls"], 2)
        self.assertEqual(row["asr_success"], 1)
        self.assertEqual(row["ai_used_tokens"], 13000)
        self.assertEqual(row["ai_limit"], 50000)
        self.assertEqual(row["ai_calls"], 2)
        self.assertTrue(row["asr_enabled"])
        self.assertTrue(row["ai_enabled"])

    def test_unlimited_limit_and_disabled_switch(self) -> None:
        uid = self._add_user("openid_2")
        get_quota(self.db, uid)
        self.db.execute(
            "UPDATE user_quotas SET asr_enabled = 0, asr_daily_seconds = 0 WHERE user_id = ?",
            (uid,),
        )
        self.db.commit()

        rows = collect_usage_summary(self.db)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertFalse(row["asr_enabled"])
        self.assertEqual(row["asr_limit"], 0)  # 0 = unlimited
        self.assertEqual(row["asr_used_seconds"], 0)
        self.assertEqual(row["ai_limit"], 0)

    def test_user_without_activity_or_quota_is_omitted(self) -> None:
        # A brand-new user with no quota row and no usage today is not listed.
        self._add_user("openid_never_active")
        rows = collect_usage_summary(self.db)
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
