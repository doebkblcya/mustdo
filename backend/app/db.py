from __future__ import annotations

import sqlite3

from app.config import get_settings
from app.time_utils import utcish_now_iso


def get_connection() -> sqlite3.Connection:
    settings = get_settings()
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    # FastAPI may create sync dependencies in a worker thread and use them in async routes.
    conn = sqlite3.connect(settings.database_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wechat_openid TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'disabled')),
                invite_redeemed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_login_at TEXT
            );

            CREATE TABLE IF NOT EXISTS invite_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code_hash TEXT NOT NULL UNIQUE,
                type TEXT NOT NULL DEFAULT 'single'
                    CHECK (type IN ('single', 'multi')),
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'redeemed', 'revoked')),
                label TEXT,
                created_at TEXT NOT NULL,
                used_at TEXT,
                used_by_user_id INTEGER REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                token_hash TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                revoked_at TEXT
            );

            CREATE TABLE IF NOT EXISTS todos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                content TEXT NOT NULL,
                due_date TEXT NOT NULL,
                due_time TEXT,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'done')),
                pinned INTEGER NOT NULL DEFAULT 0
                    CHECK (pinned IN (0, 1)),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                deleted_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_sessions_token_hash
                ON sessions(token_hash);
            CREATE INDEX IF NOT EXISTS idx_todos_user_due_date
                ON todos(user_id, due_date);
            CREATE INDEX IF NOT EXISTS idx_todos_user_deleted
                ON todos(user_id, deleted_at);
            """
        )
        _migrate_invite_codes_type(conn)
        _migrate_todos_pinned(conn)
        _migrate_users_wechat(conn)


def _migrate_users_wechat(conn: sqlite3.Connection) -> None:
    """Migration: rebuild users to the WeChat identity schema.

    The legacy schema used username/password + invite registration. We now
    identify users purely by wechat_openid. Existing (pre-WeChat) users have no
    openid and cannot log in again, so we rebuild the table. There are no real
    users yet, so no rows are preserved.
    """
    cols = {row[1] for row in conn.execute("PRAGMA table_info('users')").fetchall()}
    if "wechat_openid" in cols:
        return

    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute(
            """
            CREATE TABLE users_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wechat_openid TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'disabled')),
                invite_redeemed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_login_at TEXT
            )
            """
        )
        conn.execute("DROP TABLE users")
        conn.execute("ALTER TABLE users_new RENAME TO users")
        # Old sessions / todos / invite usage all reference pre-rebuild user
        # ids. The rebuilt users table restarts AUTOINCREMENT at 1, so without
        # cleanup the first WeChat user could read another account's todos or
        # inherit invite usage. Old (pre-WeChat) data is abandoned entirely.
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM todos")
        conn.execute(
            "UPDATE invite_codes SET used_by_user_id = NULL, used_at = NULL"
            " WHERE used_by_user_id IS NOT NULL"
        )
        conn.commit()
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def _migrate_invite_codes_type(conn: sqlite3.Connection) -> None:
    """Migration: add type column to invite_codes if it doesn't exist."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info('invite_codes')").fetchall()}
    if "type" not in cols:
        conn.execute(
            "ALTER TABLE invite_codes ADD COLUMN type TEXT NOT NULL DEFAULT 'single'"
            " CHECK (type IN ('single', 'multi'))"
        )


def _migrate_todos_pinned(conn: sqlite3.Connection) -> None:
    """Migration: add pinned column to todos if it doesn't exist."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info('todos')").fetchall()}
    if "pinned" not in cols:
        conn.execute(
            "ALTER TABLE todos ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0"
            " CHECK (pinned IN (0, 1))"
        )


def cleanup_sessions() -> int:
    """Delete expired or revoked sessions. Returns the count of removed rows."""
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM sessions WHERE expires_at <= ? OR revoked_at IS NOT NULL",
            (utcish_now_iso(),),
        )
        conn.commit()
        return cursor.rowcount
