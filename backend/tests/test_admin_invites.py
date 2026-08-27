"""Admin-console invite-code management: create once-shows-plaintext, list,
status edit render, and integration with the business redeem service."""

from __future__ import annotations

import os
import re
import sys
import tempfile
import unittest

from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.config import get_settings  # noqa: E402
from app.db import get_connection, init_db  # noqa: E402
from app.security import hash_invite_code  # noqa: E402
from app.time_utils import utcish_now_iso  # noqa: E402


CODE_RE = re.compile(r"TODO-[SM]-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}")


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


class InviteAdminTests(unittest.TestCase):
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

        # Build a fresh app each test: the module-level singleton freezes its
        # admin engine's DB path at first import, which would point at the
        # first test's database on later tests. A fresh app (and thus engine)
        # reads the current test's settings.
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

    def test_create_requires_login(self) -> None:
        c = self._client()
        for url in ("/admin/invites/new", "/admin/invite-code/list"):
            r = c.get(url, follow_redirects=False)
            self.assertIn(r.status_code, (302, 307), msg=url)

    def test_create_shows_plaintext_once_and_stores_hash(self) -> None:
        c = self._client()
        self._login(c)

        r = c.post(
            "/admin/invites/new",
            data={"type": "single", "label": "给同事A"},
            follow_redirects=False,
        )
        self.assertEqual(r.status_code, 200)
        code = CODE_RE.search(r.text)
        self.assertIsNotNone(code, msg="plaintext code should be shown once")

        with get_connection() as db:
            row = db.execute("SELECT * FROM invite_codes").fetchone()
            audit = db.execute(
                "SELECT * FROM admin_audit_logs WHERE action = 'create'"
            ).fetchone()

        self.assertEqual(row["type"], "single")
        self.assertEqual(row["status"], "active")
        self.assertEqual(row["label"], "给同事A")
        # Plaintext must be stored hashed, never verbatim.
        self.assertNotEqual(row["code_hash"], code.group(0))
        self.assertEqual(row["code_hash"], hash_invite_code(code.group(0)))
        # An audit row was written for the create action.
        self.assertIsNotNone(audit)
        self.assertEqual(audit["target_type"], "invite_codes")

    def test_list_and_edit_pages_render(self) -> None:
        c = self._client()
        self._login(c)
        c.post(
            "/admin/invites/new",
            data={"type": "multi", "label": "长期"},
            follow_redirects=False,
        )
        with get_connection() as db:
            row = db.execute("SELECT id FROM invite_codes").fetchone()
        pk = int(row["id"])

        r = c.get("/admin/invite-code/list")
        self.assertEqual(r.status_code, 200)
        self.assertIn("长期", r.text)

        r = c.get(f"/admin/invite-code/edit/{pk}")
        self.assertEqual(r.status_code, 200)

    def test_created_code_is_redeemable(self) -> None:
        c = self._client()
        self._login(c)
        r = c.post(
            "/admin/invites/new",
            data={"type": "single", "label": ""},
            follow_redirects=False,
        )
        code = CODE_RE.search(r.text).group(0)

        from app.services.invite_gate import redeem_invite

        uid = _create_user("o_test")
        with get_connection() as db:
            redeem_invite(db, uid, code)

        with get_connection() as db:
            row = db.execute("SELECT * FROM invite_codes").fetchone()
            user = db.execute(
                "SELECT invite_redeemed_at FROM users WHERE id = ?", (uid,)
            ).fetchone()

        # single code -> redeemed after use, bound to the user.
        self.assertEqual(row["status"], "redeemed")
        self.assertEqual(row["used_by_user_id"], uid)
        self.assertIsNotNone(user["invite_redeemed_at"])

    def test_invalid_type_rejected(self) -> None:
        c = self._client()
        self._login(c)
        r = c.post(
            "/admin/invites/new",
            data={"type": "bogus", "label": ""},
            follow_redirects=False,
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn("类型无效", r.text)
        with get_connection() as db:
            count = db.execute("SELECT COUNT(*) c FROM invite_codes").fetchone()["c"]
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
