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

from app.config import get_settings  # noqa: E402
from app.db import get_connection, init_db  # noqa: E402
from app.deps import current_user_invited  # noqa: E402
from app.security import hash_invite_code  # noqa: E402
from app.services.invite_gate import redeem_invite  # noqa: E402
from app.time_utils import utcish_now_iso  # noqa: E402


class InviteGateTests(unittest.TestCase):
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

    def _create_user(self, openid: str = "openid-1") -> int:
        now = utcish_now_iso()
        db = get_connection()
        try:
            cursor = db.execute(
                """
                INSERT INTO users (wechat_openid, status, created_at, updated_at)
                VALUES (?, 'active', ?, ?)
                """,
                (openid, now, now),
            )
            db.commit()
            return int(cursor.lastrowid)
        finally:
            db.close()

    def _create_invite(self, code: str, invite_type: str = "single") -> int:
        now = utcish_now_iso()
        db = get_connection()
        try:
            cursor = db.execute(
                """
                INSERT INTO invite_codes (code_hash, type, status, label, created_at)
                VALUES (?, ?, 'active', '测试', ?)
                """,
                (hash_invite_code(code), invite_type, now),
            )
            db.commit()
            return int(cursor.lastrowid)
        finally:
            db.close()

    def test_redeem_single_marks_redeemed_and_sets_flag(self) -> None:
        user_id = self._create_user()
        code = "TODO-S-AAAA-BBBB-CCCC"
        invite_id = self._create_invite(code, "single")

        db = get_connection()
        try:
            redeem_invite(db, user_id, code)
            user = db.execute(
                "SELECT invite_redeemed_at FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            invite = db.execute(
                "SELECT status, used_by_user_id FROM invite_codes WHERE id = ?", (invite_id,)
            ).fetchone()
        finally:
            db.close()

        self.assertIsNotNone(user["invite_redeemed_at"])
        self.assertEqual(invite["status"], "redeemed")
        self.assertEqual(invite["used_by_user_id"], user_id)

    def test_redeem_multi_stays_active(self) -> None:
        user_id = self._create_user()
        code = "TODO-M-AAAA-BBBB-CCCC"
        invite_id = self._create_invite(code, "multi")

        db = get_connection()
        try:
            redeem_invite(db, user_id, code)
            user = db.execute(
                "SELECT invite_redeemed_at FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            invite = db.execute(
                "SELECT status FROM invite_codes WHERE id = ?", (invite_id,)
            ).fetchone()
        finally:
            db.close()

        self.assertIsNotNone(user["invite_redeemed_at"])
        self.assertEqual(invite["status"], "active")

    def test_already_redeemed_raises_409(self) -> None:
        user_id = self._create_user()
        code = "TODO-S-AAAA-BBBB-CCCC"
        self._create_invite(code, "single")

        db = get_connection()
        try:
            redeem_invite(db, user_id, code)
            with self.assertRaises(HTTPException) as raised:
                redeem_invite(db, user_id, code)
        finally:
            db.close()

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail["code"], "already_redeemed")

    def test_invalid_code_raises_400(self) -> None:
        user_id = self._create_user()
        db = get_connection()
        try:
            with self.assertRaises(HTTPException) as raised:
                redeem_invite(db, user_id, "TODO-S-WRNG-WRNG-WRNG")
        finally:
            db.close()

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(raised.exception.detail["code"], "invalid_invite_code")

    def test_current_user_invited_blocks_unredeemed(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            current_user_invited(user={"id": 1, "invite_redeemed_at": None})
        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(raised.exception.detail["code"], "invite_required")

        user = current_user_invited(
            user={"id": 1, "invite_redeemed_at": utcish_now_iso()}
        )
        self.assertEqual(user["id"], 1)


if __name__ == "__main__":
    unittest.main()
