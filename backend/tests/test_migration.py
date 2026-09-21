from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from app.config import get_settings  # noqa: E402
from app.db import init_db  # noqa: E402


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


LEGACY_SCHEMA = """
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    username_normalized TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_login_at TEXT
);

CREATE TABLE invite_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code_hash TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL DEFAULT 'single',
    status TEXT NOT NULL DEFAULT 'active',
    label TEXT,
    created_at TEXT NOT NULL,
    used_at TEXT,
    used_by_user_id INTEGER REFERENCES users(id)
);

CREATE TABLE sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT
);

CREATE TABLE todos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    due_date TEXT NOT NULL,
    due_time TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    pinned INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT
);
"""


class LegacyMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "legacy.db")
        self.env = patch.dict(
            os.environ,
            {"DATABASE_PATH": self.db_path, "SECRET_KEY": "test-secret"},
            clear=False,
        )
        self.env.start()
        get_settings.cache_clear()

    def tearDown(self) -> None:
        self.env.stop()
        self.tmpdir.cleanup()
        get_settings.cache_clear()

    def _seed_legacy_db(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.executescript(LEGACY_SCHEMA)
            conn.execute(
                """
                INSERT INTO users (username, username_normalized, password_hash,
                                   status, created_at, updated_at)
                VALUES ('legacy', 'legacy', 'hash', 'active', 'now', 'now')
                """
            )
            conn.execute(
                """
                INSERT INTO invite_codes (code_hash, type, status, label,
                                          created_at, used_at, used_by_user_id)
                VALUES ('hash1', 'single', 'redeemed', 'old', 'now', 'now', 1)
                """
            )
            conn.execute(
                """
                INSERT INTO sessions (user_id, token_hash, created_at, expires_at)
                VALUES (1, 'token1', 'now', '2099-01-01T00:00:00')
                """
            )
            conn.execute(
                """
                INSERT INTO todos (user_id, content, due_date, due_time, status,
                                   pinned, created_at, updated_at)
                VALUES (1, '旧待办', '2026-08-01', NULL, 'pending', 0, 'now', 'now')
                """
            )
            conn.commit()
        finally:
            conn.close()

    def test_migration_clears_all_user_associated_data(self) -> None:
        self._seed_legacy_db()
        init_db()

        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            users = conn.execute("SELECT * FROM users").fetchall()
            todos = conn.execute("SELECT * FROM todos").fetchall()
            sessions = conn.execute("SELECT * FROM sessions").fetchall()
            user_cols = [
                c[1] for c in conn.execute("PRAGMA table_info('users')").fetchall()
            ]
            todo_cols = [
                c[1] for c in conn.execute("PRAGMA table_info('todos')").fetchall()
            ]
            invite_table = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'invite_codes'"
            ).fetchone()
        finally:
            conn.close()

        # users rebuilt: no legacy rows, new identity columns present
        self.assertEqual(len(users), 0)
        self.assertEqual(
            user_cols,
            [
                "id",
                "wechat_openid",
                "admin_remark",
                "status",
                "created_at",
                "updated_at",
                "last_login_at",
            ],
        )
        # no orphaned todos / sessions pointing at a reused id
        self.assertEqual(len(todos), 0)
        self.assertEqual(len(sessions), 0)
        self.assertIn("persistent", todo_cols)
        self.assertIsNone(invite_table)

    def test_current_schema_removes_gate_and_converts_daily_limits_to_totals(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.executescript(
                """
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    wechat_openid TEXT UNIQUE,
                    status TEXT NOT NULL DEFAULT 'active',
                    invite_redeemed_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_login_at TEXT
                );
                CREATE TABLE invite_codes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code_hash TEXT NOT NULL UNIQUE,
                    type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    token_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT
                );
                CREATE TABLE user_quotas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
                    asr_enabled INTEGER NOT NULL DEFAULT 1,
                    asr_daily_seconds REAL NOT NULL DEFAULT 0,
                    ai_enabled INTEGER NOT NULL DEFAULT 1,
                    ai_daily_tokens INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE admin_audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    admin_id INTEGER,
                    action TEXT NOT NULL,
                    target_type TEXT,
                    target_id INTEGER,
                    detail TEXT,
                    created_at TEXT NOT NULL
                );
                INSERT INTO users
                    (wechat_openid, status, invite_redeemed_at, created_at, updated_at)
                VALUES
                    ('openid-1', 'active', 'now', 'now', 'now'),
                    ('openid-2', 'active', NULL, 'now', 'now');
                INSERT INTO invite_codes (code_hash, type, status, created_at)
                VALUES ('hash1', 'single', 'active', 'now');
                INSERT INTO user_quotas
                    (user_id, asr_daily_seconds, ai_daily_tokens, created_at, updated_at)
                VALUES (1, 0, 0, 'now', 'now');
                INSERT INTO sessions (user_id, token_hash, created_at, expires_at)
                VALUES (2, 'unadmitted-session', 'now', '2099-01-01T00:00:00');
                INSERT INTO admin_audit_logs
                    (action, target_type, detail, created_at)
                VALUES
                    ('create', 'invite_code', 'created invite', 'now'),
                    ('login', 'admin', 'normal record', 'now');
                """
            )
            conn.commit()
        finally:
            conn.close()

        init_db()

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            user_cols = [row[1] for row in conn.execute("PRAGMA table_info('users')")]
            quota_cols = [row[1] for row in conn.execute("PRAGMA table_info('user_quotas')")]
            quotas = conn.execute(
                "SELECT * FROM user_quotas ORDER BY user_id"
            ).fetchall()
            users = conn.execute("SELECT id FROM users ORDER BY id").fetchall()
            unadmitted_sessions = conn.execute(
                "SELECT id FROM sessions WHERE user_id = 2"
            ).fetchall()
            invite_table = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'invite_codes'"
            ).fetchone()
            audit_rows = conn.execute(
                "SELECT target_type, detail FROM admin_audit_logs ORDER BY id"
            ).fetchall()
        finally:
            conn.close()

        self.assertNotIn("invite_redeemed_at", user_cols)
        self.assertIn("admin_remark", user_cols)
        self.assertIn("asr_total_seconds", quota_cols)
        self.assertIn("ai_total_tokens", quota_cols)
        self.assertNotIn("asr_daily_seconds", quota_cols)
        self.assertNotIn("ai_daily_tokens", quota_cols)
        self.assertEqual([row["id"] for row in users], [1])
        self.assertEqual(unadmitted_sessions, [])
        self.assertEqual(len(quotas), 1)
        self.assertTrue(all(row["asr_total_seconds"] == 1200 for row in quotas))
        self.assertTrue(all(row["ai_total_tokens"] == 300000 for row in quotas))
        self.assertIsNone(invite_table)
        self.assertEqual([(row["target_type"], row["detail"]) for row in audit_rows], [("admin", "normal record")])


if __name__ == "__main__":
    unittest.main()
