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
                admin_remark TEXT,
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'disabled')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_login_at TEXT
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
                asr_total_seconds REAL NOT NULL DEFAULT 1200,
                ai_enabled INTEGER NOT NULL DEFAULT 1
                    CHECK (ai_enabled IN (0, 1)),
                ai_total_tokens INTEGER NOT NULL DEFAULT 300000,
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
        _migrate_todos_pinned(conn)
        _migrate_users_wechat(conn)
        _migrate_user_quotas_to_totals(conn)
        _remove_invite_schema(conn)
        _migrate_users_admin_remark(conn)
        _ensure_all_users_have_quotas(conn)


def _migrate_users_wechat(conn: sqlite3.Connection) -> None:
    """Migration: rebuild users to the WeChat identity schema.

    The legacy schema used username/password registration. We now identify
    users purely by wechat_openid. Existing (pre-WeChat) users have no openid
    and cannot log in again, so we rebuild the table. There are no real users
    yet, so no rows are preserved.
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
                admin_remark TEXT,
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'disabled')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_login_at TEXT
            )
            """
        )
        conn.execute("DROP TABLE users")
        conn.execute("ALTER TABLE users_new RENAME TO users")
        # Old sessions and todos reference pre-rebuild user ids. The rebuilt
        # users table restarts AUTOINCREMENT at 1, so without cleanup the first
        # WeChat user could read another account's todos. Old (pre-WeChat) data
        # is abandoned entirely.
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM todos")
        conn.commit()
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def _migrate_user_quotas_to_totals(conn: sqlite3.Connection) -> None:
    """Replace the former daily caps with lifetime total allowances.

    Existing zero values were the old lazy-created unlimited defaults. During
    this one-time column migration they become the configured public defaults;
    future zero values remain a deliberate administrator override for
    unlimited access.
    """
    cols = {row[1] for row in conn.execute("PRAGMA table_info('user_quotas')").fetchall()}
    migrated_asr = "asr_daily_seconds" in cols and "asr_total_seconds" not in cols
    migrated_ai = "ai_daily_tokens" in cols and "ai_total_tokens" not in cols
    if migrated_asr:
        conn.execute("ALTER TABLE user_quotas RENAME COLUMN asr_daily_seconds TO asr_total_seconds")
    if migrated_ai:
        conn.execute("ALTER TABLE user_quotas RENAME COLUMN ai_daily_tokens TO ai_total_tokens")

    settings = get_settings()
    if migrated_asr:
        conn.execute(
            "UPDATE user_quotas SET asr_total_seconds = ? WHERE asr_total_seconds = 0",
            (max(0.0, settings.default_asr_total_seconds),),
        )
    if migrated_ai:
        conn.execute(
            "UPDATE user_quotas SET ai_total_tokens = ? WHERE ai_total_tokens = 0",
            (max(0, settings.default_ai_total_tokens),),
        )


def _remove_invite_schema(conn: sqlite3.Connection) -> None:
    """Keep previously admitted users, then permanently remove the old gate.

    This runs only while the retired marker column still exists. Accounts that
    never passed the old gate are discarded with their cascaded sessions and
    business data; subsequent direct-login accounts are unaffected because the
    marker column no longer exists after this migration.
    """
    user_cols = {row[1] for row in conn.execute("PRAGMA table_info('users')").fetchall()}
    conn.execute("DROP TABLE IF EXISTS invite_codes")
    if "invite_redeemed_at" in user_cols:
        conn.execute("DELETE FROM users WHERE invite_redeemed_at IS NULL")
    conn.execute(
        """
        DELETE FROM admin_audit_logs
        WHERE lower(COALESCE(target_type, '')) LIKE '%invite%'
           OR lower(COALESCE(detail, '')) LIKE '%invite%'
           OR COALESCE(detail, '') LIKE '%邀请码%'
        """
    )
    if "invite_redeemed_at" in user_cols:
        conn.execute("ALTER TABLE users DROP COLUMN invite_redeemed_at")


def _ensure_all_users_have_quotas(conn: sqlite3.Connection) -> None:
    """Backfill a default quota row for every existing user."""
    settings = get_settings()
    now = utcish_now_iso()
    conn.execute(
        """
        INSERT OR IGNORE INTO user_quotas
            (user_id, asr_enabled, asr_total_seconds, ai_enabled,
             ai_total_tokens, created_at, updated_at)
        SELECT id, 1, ?, 1, ?, ?, ? FROM users
        """,
        (
            max(0.0, settings.default_asr_total_seconds),
            max(0, settings.default_ai_total_tokens),
            now,
            now,
        ),
    )


def _migrate_users_admin_remark(conn: sqlite3.Connection) -> None:
    """Add the optional private admin label to an existing users table."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info('users')").fetchall()}
    if "admin_remark" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN admin_remark TEXT")


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
