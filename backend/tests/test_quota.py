from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.admin_security import hash_password, verify_password  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import get_connection, init_db  # noqa: E402
from app.services.quota import (  # noqa: E402
    CODE_AI_DISABLED,
    CODE_AI_QUOTA_EXCEEDED,
    CODE_ASR_DISABLED,
    CODE_ASR_QUOTA_EXCEEDED,
    ai_used_tokens_today,
    asr_used_seconds_today,
    check_ai_quota,
    check_asr_quota,
    get_quota,
    record_ai_usage,
    record_asr_usage,
)
from app.time_utils import utcish_now_iso  # noqa: E402


class AdminSecurityTests(unittest.TestCase):
    def test_hash_and_verify_roundtrip(self) -> None:
        h = hash_password("correct horse battery staple")
        self.assertTrue(verify_password("correct horse battery staple", h))
        self.assertFalse(verify_password("wrong", h))

    def test_hash_is_salted(self) -> None:
        self.assertNotEqual(hash_password("same"), hash_password("same"))

    def test_verify_rejects_malformed(self) -> None:
        self.assertFalse(verify_password("x", "not-a-hash"))
        self.assertFalse(verify_password("x", "md5$$$"))


class QuotaTests(unittest.TestCase):
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
        self.db.execute(
            "INSERT INTO users (wechat_openid, status, created_at, updated_at) VALUES (?,?,?,?)",
            ("openid_1", "active", utcish_now_iso(), utcish_now_iso()),
        )
        self.db.commit()
        self.user_id = self.db.execute(
            "SELECT id FROM users WHERE wechat_openid = 'openid_1'"
        ).fetchone()["id"]

    def tearDown(self) -> None:
        self.db.close()
        self.env.stop()
        self.tmpdir.cleanup()
        get_settings.cache_clear()

    def _set_quota(self, **kwargs) -> None:
        now = utcish_now_iso()
        self.db.execute(
            """
            INSERT INTO user_quotas
                (user_id, asr_enabled, asr_daily_seconds, ai_enabled, ai_daily_tokens, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                asr_enabled=excluded.asr_enabled,
                asr_daily_seconds=excluded.asr_daily_seconds,
                ai_enabled=excluded.ai_enabled,
                ai_daily_tokens=excluded.ai_daily_tokens,
                updated_at=excluded.updated_at
            """,
            (
                self.user_id,
                kwargs.get("asr_enabled", 1),
                kwargs.get("asr_daily_seconds", 0),
                kwargs.get("ai_enabled", 1),
                kwargs.get("ai_daily_tokens", 0),
                now,
                now,
            ),
        )
        self.db.commit()

    def test_get_quota_creates_unlimited_default(self) -> None:
        q = get_quota(self.db, self.user_id)
        self.assertEqual(q["asr_enabled"], 1)
        self.assertEqual(q["asr_daily_seconds"], 0)
        self.assertEqual(q["ai_enabled"], 1)
        self.assertEqual(q["ai_daily_tokens"], 0)

    def test_asr_disabled_raises(self) -> None:
        self._set_quota(asr_enabled=0)
        with self.assertRaises(HTTPException) as raised:
            check_asr_quota(self.db, self.user_id, 5.0)
        self.assertEqual(raised.exception.detail["code"], CODE_ASR_DISABLED)

    def test_asr_quota_exceeded(self) -> None:
        self._set_quota(asr_daily_seconds=100)
        record_asr_usage(
            self.db, self.user_id,
            request_id="r1", logid=None, audio_seconds=95.0,
            status="success", error_code=None, duration_ms=100,
        )
        self.assertAlmostEqual(asr_used_seconds_today(self.db, self.user_id), 95.0)
        with self.assertRaises(HTTPException) as raised:
            check_asr_quota(self.db, self.user_id, 10.0)  # 95 + 10 > 100
        self.assertEqual(raised.exception.detail["code"], CODE_ASR_QUOTA_EXCEEDED)

    def test_asr_quota_within_limit_ok(self) -> None:
        self._set_quota(asr_daily_seconds=100)
        record_asr_usage(
            self.db, self.user_id,
            request_id="r1", logid=None, audio_seconds=40.0,
            status="success", error_code=None, duration_ms=100,
        )
        check_asr_quota(self.db, self.user_id, 10.0)  # 40 + 10 <= 100, no raise

    def test_ai_disabled_raises(self) -> None:
        self._set_quota(ai_enabled=0)
        with self.assertRaises(HTTPException) as raised:
            check_ai_quota(self.db, self.user_id)
        self.assertEqual(raised.exception.detail["code"], CODE_AI_DISABLED)

    def test_ai_quota_soft_cap(self) -> None:
        self._set_quota(ai_daily_tokens=1000)
        record_ai_usage(
            self.db, self.user_id,
            purpose="parse", status="success",
            prompt_tokens=0, completion_tokens=0, total_tokens=1000,
            cache_hit_tokens=0, cache_miss_tokens=0, error_code=None, duration_ms=100,
        )
        self.assertEqual(ai_used_tokens_today(self.db, self.user_id), 1000)
        with self.assertRaises(HTTPException) as raised:
            check_ai_quota(self.db, self.user_id)
        self.assertEqual(raised.exception.detail["code"], CODE_AI_QUOTA_EXCEEDED)

    def test_unlimited_limits_pass(self) -> None:
        # Default unlimited: no quota rows, never raises even with usage.
        record_asr_usage(
            self.db, self.user_id,
            request_id="r1", logid=None, audio_seconds=9999.0,
            status="success", error_code=None, duration_ms=100,
        )
        check_asr_quota(self.db, self.user_id, 9999.0)
        record_ai_usage(
            self.db, self.user_id,
            purpose="parse", status="success",
            prompt_tokens=0, completion_tokens=0, total_tokens=999999,
            cache_hit_tokens=0, cache_miss_tokens=0, error_code=None, duration_ms=100,
        )
        check_ai_quota(self.db, self.user_id)


if __name__ == "__main__":
    unittest.main()
