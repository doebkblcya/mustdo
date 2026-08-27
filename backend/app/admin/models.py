"""SQLAlchemy models for the SQLAdmin console.

Only the tables the admin console needs are mapped. The business API keeps
using native ``sqlite3``; this ORM is a read/write projection onto the SAME
SQLite database for the console only.

Permission grid (enforced in ``ModelView`` subclasses):
- ``users``            -> read-only (identity data)
- ``admins``           -> read-only (managed by the CLI script)
- ``asr_usage``        -> read-only
- ``ai_usage``         -> read-only
- ``user_quotas``      -> edit/delete (service switch + limits)
"""

from __future__ import annotations

from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.time_utils import utcish_now_iso


def _now_iso() -> str:
    return utcish_now_iso()


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    wechat_openid: Mapped[str] = mapped_column(unique=True)
    status: Mapped[str]
    invite_redeemed_at: Mapped[str | None]
    created_at: Mapped[str]
    updated_at: Mapped[str]
    last_login_at: Mapped[str | None]


class Admin(Base):
    __tablename__ = "admins"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str]
    username_normalized: Mapped[str] = mapped_column(unique=True)
    password_hash: Mapped[str]
    session_version: Mapped[int]
    status: Mapped[str]
    created_at: Mapped[str]
    updated_at: Mapped[str]
    last_login_at: Mapped[str | None]


class UserQuota(Base):
    __tablename__ = "user_quotas"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    user: Mapped[User] = relationship()
    asr_enabled: Mapped[int]
    asr_daily_seconds: Mapped[float]
    ai_enabled: Mapped[int]
    ai_daily_tokens: Mapped[int]
    created_at: Mapped[str] = mapped_column(default=_now_iso)
    updated_at: Mapped[str] = mapped_column(default=_now_iso)


class AsrUsage(Base):
    __tablename__ = "asr_usage"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    request_id: Mapped[str]
    logid: Mapped[str | None]
    audio_seconds: Mapped[float]
    status: Mapped[str]
    error_code: Mapped[str | None]
    duration_ms: Mapped[int]
    created_at: Mapped[str]


class AiUsage(Base):
    __tablename__ = "ai_usage"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    purpose: Mapped[str]
    status: Mapped[str]
    prompt_tokens: Mapped[int]
    completion_tokens: Mapped[int]
    total_tokens: Mapped[int]
    cache_hit_tokens: Mapped[int]
    cache_miss_tokens: Mapped[int]
    error_code: Mapped[str | None]
    duration_ms: Mapped[int]
    created_at: Mapped[str]


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    admin_id: Mapped[int | None] = mapped_column(ForeignKey("admins.id"))
    username: Mapped[str | None]
    action: Mapped[str]
    target_type: Mapped[str | None]
    target_id: Mapped[str | None]
    detail: Mapped[str | None]
    created_at: Mapped[str]
