from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.config import get_settings  # noqa: E402
from app.db import get_connection, init_db  # noqa: E402
from app.routers.auth import me, my_quota, wechat_login  # noqa: E402
from app.schemas import WechatLoginRequest  # noqa: E402
from app.services.wechat import WechatLoginError, exchange_code_for_openid  # noqa: E402
class WechatLoginAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.env = patch.dict(
            os.environ,
            {
                "DATABASE_PATH": os.path.join(self.tmpdir.name, "test.db"),
                "SECRET_KEY": "test-secret",
                "WECHAT_APP_ID": "wx-test",
                "WECHAT_APP_SECRET": "test-secret",
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

    def _db(self):
        return get_connection()

    def test_first_login_creates_user_and_default_quota(self) -> None:
        async def run():
            db = self._db()
            try:
                with patch(
                    "app.routers.auth.exchange_code_for_openid",
                    AsyncMock(return_value="openid-abc"),
                ):
                    result = await wechat_login(WechatLoginRequest(code="code1"), db=db)
                row = db.execute(
                    "SELECT id, wechat_openid FROM users WHERE id = ?",
                    (result.user.id,),
                ).fetchone()
                quota = db.execute(
                    "SELECT * FROM user_quotas WHERE user_id = ?",
                    (result.user.id,),
                ).fetchone()
            finally:
                db.close()
            return result, row, quota

        result, row, quota = asyncio.run(run())

        self.assertTrue(result.user.id)
        self.assertEqual(result.token_type, "bearer")
        self.assertTrue(result.token)
        self.assertEqual(row["wechat_openid"], "openid-abc")
        self.assertEqual(quota["asr_total_seconds"], 1200)
        self.assertEqual(quota["ai_total_tokens"], 300000)

    def test_same_openid_returns_same_user(self) -> None:
        async def run():
            db = self._db()
            try:
                with patch(
                    "app.routers.auth.exchange_code_for_openid",
                    AsyncMock(return_value="openid-abc"),
                ):
                    first = await wechat_login(WechatLoginRequest(code="code1"), db=db)
                with patch(
                    "app.routers.auth.exchange_code_for_openid",
                    AsyncMock(return_value="openid-abc"),
                ):
                    second = await wechat_login(WechatLoginRequest(code="code2"), db=db)
            finally:
                db.close()
            return first, second

        first, second = asyncio.run(run())

        self.assertEqual(second.user.id, first.user.id)

    def test_quota_endpoint_reports_total_used_and_remaining(self) -> None:
        async def run():
            db = self._db()
            try:
                with patch(
                    "app.routers.auth.exchange_code_for_openid",
                    AsyncMock(return_value="openid-quota"),
                ):
                    result = await wechat_login(WechatLoginRequest(code="code1"), db=db)
                db.execute(
                    """
                    INSERT INTO asr_usage
                        (user_id, request_id, audio_seconds, status, duration_ms, created_at)
                    VALUES (?, 'old-request', 600, 'success', 10, '2020-01-01T00:00:00')
                    """,
                    (result.user.id,),
                )
                db.execute(
                    """
                    INSERT INTO ai_usage
                        (user_id, purpose, status, total_tokens, duration_ms, created_at)
                    VALUES (?, 'parse', 'success', 30000, 10, '2020-01-01T00:00:00')
                    """,
                    (result.user.id,),
                )
                db.commit()
                quota = my_quota(db=db, user={"id": result.user.id})
            finally:
                db.close()
            return quota

        quota = asyncio.run(run())
        self.assertEqual(quota.asr.total_seconds, 1200)
        self.assertEqual(quota.asr.used_seconds, 600)
        self.assertEqual(quota.asr.remaining_seconds, 600)
        self.assertEqual(quota.ai.total_tokens, 300000)
        self.assertEqual(quota.ai.used_tokens, 30000)
        self.assertEqual(quota.ai.remaining_tokens, 270000)

    def test_disabled_user_is_rejected(self) -> None:
        async def run():
            db = self._db()
            try:
                with patch(
                    "app.routers.auth.exchange_code_for_openid",
                    AsyncMock(return_value="openid-disabled"),
                ):
                    created = await wechat_login(WechatLoginRequest(code="code1"), db=db)
                db.execute("UPDATE users SET status = 'disabled' WHERE id = ?", (created.user.id,))
                db.commit()
                with patch(
                    "app.routers.auth.exchange_code_for_openid",
                    AsyncMock(return_value="openid-disabled"),
                ):
                    with self.assertRaises(HTTPException) as raised:
                        await wechat_login(WechatLoginRequest(code="code2"), db=db)
            finally:
                db.close()
            return raised

        raised = asyncio.run(run())
        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(raised.exception.detail["code"], "account_disabled")

    def test_wechat_service_error_propagates_machine_code(self) -> None:
        async def run():
            db = self._db()
            try:
                with patch(
                    "app.routers.auth.exchange_code_for_openid",
                    AsyncMock(
                        side_effect=WechatLoginError(
                            "wechat_service_error",
                            "微信服务暂不可用，请重试",
                            502,
                        )
                    ),
                ):
                    with self.assertRaises(HTTPException) as raised:
                        await wechat_login(WechatLoginRequest(code="code1"), db=db)
            finally:
                db.close()
            return raised

        raised = asyncio.run(run())
        self.assertEqual(raised.exception.status_code, 502)
        self.assertEqual(raised.exception.detail["code"], "wechat_service_error")

    def test_me_returns_user_id(self) -> None:
        async def run():
            db = self._db()
            try:
                with patch(
                    "app.routers.auth.exchange_code_for_openid",
                    AsyncMock(return_value="openid-abc"),
                ):
                    result = await wechat_login(WechatLoginRequest(code="code1"), db=db)
                public = me(user={"id": result.user.id})
            finally:
                db.close()
            return public

        public = asyncio.run(run())
        self.assertIsInstance(public.id, int)
        self.assertFalse(hasattr(public, "username"))


class WechatServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {
                "WECHAT_APP_ID": "wx-test",
                "WECHAT_APP_SECRET": "secret",
            },
            clear=False,
        )
        self.env.start()
        get_settings.cache_clear()

    def tearDown(self) -> None:
        self.env.stop()
        get_settings.cache_clear()

    def test_missing_config_raises_wechat_config_missing(self) -> None:
        with patch.dict(os.environ, {"WECHAT_APP_ID": "", "WECHAT_APP_SECRET": ""}, clear=False):
            get_settings.cache_clear()
            with self.assertRaises(WechatLoginError) as raised:
                asyncio.run(exchange_code_for_openid("code1"))

        self.assertEqual(raised.exception.code, "wechat_config_missing")
        self.assertEqual(raised.exception.http_status, 500)

    def test_exchange_returns_openid_and_ignores_session_key(self) -> None:
        class FakeResp:
            def json(self):
                return {"openid": "openid-xyz", "session_key": "SHOULD-BE-DISCARDED"}

        async def run():
            with patch(
                "app.services.wechat.get_wechat_client",
                return_value=SimpleNamespace(
                    get=AsyncMock(return_value=FakeResp())
                ),
            ):
                return await exchange_code_for_openid("code1")

        openid = asyncio.run(run())
        self.assertEqual(openid, "openid-xyz")

    def test_error_errcode_maps_to_machine_code(self) -> None:
        class FakeResp:
            def json(self):
                return {"errcode": 40029, "errmsg": "invalid code"}

        async def run():
            with patch(
                "app.services.wechat.get_wechat_client",
                return_value=SimpleNamespace(get=AsyncMock(return_value=FakeResp())),
            ):
                with self.assertRaises(WechatLoginError) as raised:
                    await exchange_code_for_openid("code1")
            return raised

        raised = asyncio.run(run())
        self.assertEqual(raised.exception.code, "wechat_code_invalid")
        self.assertEqual(raised.exception.http_status, 400)


if __name__ == "__main__":
    unittest.main()
