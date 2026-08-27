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

            -- ============================================================
            -- 待办提醒（微信订阅消息）
            -- todo_id UNIQUE：每条待办同时保留一个有效提醒（upsert 覆盖）
            -- ============================================================

            CREATE TABLE IF NOT EXISTS todo_reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                todo_id INTEGER NOT NULL UNIQUE REFERENCES todos(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                remind_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'sent', 'failed', 'cancelled')),
                created_at TEXT NOT NULL,
                sent_at TEXT,
                error_code TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_todo_reminders_status_remind_at
                ON todo_reminders(status, remind_at);

            -- ============================================================
            -- Admin console tables (separate from WeChat-user identity)
            -- ============================================================

            CREATE TABLE IF NOT EXISTS admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                username_normalized TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                session_version INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'disabled')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_login_at TEXT
            );

            CREATE TABLE IF NOT EXISTS user_quotas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
                asr_enabled INTEGER NOT NULL DEFAULT 1
                    CHECK (asr_enabled IN (0, 1)),
                asr_daily_seconds REAL NOT NULL DEFAULT 0,
                ai_enabled INTEGER NOT NULL DEFAULT 1
                    CHECK (ai_enabled IN (0, 1)),
                ai_daily_tokens INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS asr_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                request_id TEXT NOT NULL,
                logid TEXT,
                audio_seconds REAL NOT NULL,
                status TEXT NOT NULL
                    CHECK (status IN ('success', 'silence', 'failed')),
                error_code TEXT,
                duration_ms INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS ai_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                purpose TEXT NOT NULL
                    CHECK (purpose IN ('parse', 'organize')),
                status TEXT NOT NULL
                    CHECK (status IN ('success', 'failed')),
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                cache_hit_tokens INTEGER NOT NULL DEFAULT 0,
                cache_miss_tokens INTEGER NOT NULL DEFAULT 0,
                error_code TEXT,
                duration_ms INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS admin_audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER REFERENCES admins(id),
                username TEXT,
                action TEXT NOT NULL,
                target_type TEXT,
                target_id TEXT,
                detail TEXT,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_user_quotas_user
                ON user_quotas(user_id);
            CREATE INDEX IF NOT EXISTS idx_asr_usage_user_created
                ON asr_usage(user_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_ai_usage_user_created
                ON ai_usage(user_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_admin_audit_created
                ON admin_audit_logs(created_at);
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
