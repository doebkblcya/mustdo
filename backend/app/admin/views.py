"""ModelView definitions for the Mustdo admin console.

Enforces the permission grid:
- users / admins / asr_usage / ai_usage -> read-only
- user_quotas                         -> can edit (and create a row),
                                          i.e. the only writable management table.

Model binding must use the ``ModelView, model=...`` class-keyword form required
by SQLAdmin's metaclass. Config attributes are ``ClassVar`` (list/dict) so the
mutable-default lint (RUF012) stays quiet.
"""

from __future__ import annotations

from typing import ClassVar

from sqladmin import ModelView

from app.admin.models import Admin, AdminAuditLog, AiUsage, AsrUsage, User, UserQuota


class UserView(ModelView, model=User):
    """WeChat-user identity data: read-only."""

    name = "用户"
    name_plural = "用户"
    icon = "fa-user"
    category = "用户与配额"

    column_list: ClassVar[list[str]] = [
        "id",
        "wechat_openid",
        "status",
        "invite_redeemed_at",
        "created_at",
        "updated_at",
    ]
    column_labels: ClassVar[dict[str, str]] = {
        "id": "ID",
        "wechat_openid": "微信 OpenID",
        "status": "状态",
        "invite_redeemed_at": "绑定邀请时间",
        "created_at": "创建时间",
        "updated_at": "更新时间",
    }
    column_searchable_list: ClassVar[list[str]] = ["wechat_openid"]
    column_sortable_list: ClassVar[list[str]] = ["id", "created_at", "status"]
    column_default_sort: ClassVar[list[tuple[str, bool]]] = [("id", False)]

    can_create = False
    can_edit = False
    can_delete = False


class UserQuotaView(ModelView, model=UserQuota):
    """Per-user ASR/AI switches and daily limits: the pool admin edits."""

    name = "服务配额"
    name_plural = "服务配额"
    icon = "fa-sliders"
    category = "用户与配额"

    column_list: ClassVar[list[str]] = [
        "id",
        "user_id",
        "asr_enabled",
        "asr_daily_seconds",
        "ai_enabled",
        "ai_daily_tokens",
        "updated_at",
    ]
    column_labels: ClassVar[dict[str, str]] = {
        "id": "ID",
        "user_id": "用户ID",
        "asr_enabled": "ASR 开关",
        "asr_daily_seconds": "ASR 每日时长(秒)",
        "ai_enabled": "AI 开关",
        "ai_daily_tokens": "AI 每日Token限额",
        "updated_at": "更新时间",
    }
    column_searchable_list: ClassVar[list[str]] = ["user_id"]
    column_sortable_list: ClassVar[list[str]] = [
        "id",
        "user_id",
        "asr_daily_seconds",
        "ai_daily_tokens",
        "updated_at",
    ]

    form_columns: ClassVar[list[str]] = [
        "user",
        "asr_enabled",
        "asr_daily_seconds",
        "ai_enabled",
        "ai_daily_tokens",
    ]
    form_labels: ClassVar[dict[str, str]] = {
        "user": "用户",
        "user_id": "用户ID",
        "asr_enabled": "ASR 开关",
        "asr_daily_seconds": "ASR 每日时长(秒)",
        "ai_enabled": "AI 开关",
        "ai_daily_tokens": "AI 每日Token限额",
    }
    # 0 表示不限；服务开关用 0/1 展示。
    can_create = True
    can_edit = True
    can_delete = False


class AsrUsageView(ModelView, model=AsrUsage):
    """ASR usage events: read-only ledger."""

    name = "ASR 用量"
    name_plural = "ASR 用量"
    icon = "fa-microphone"
    category = "用量"

    column_list: ClassVar[list[str]] = [
        "id",
        "user_id",
        "request_id",
        "audio_seconds",
        "status",
        "duration_ms",
        "created_at",
    ]
    column_labels: ClassVar[dict[str, str]] = {
        "id": "ID",
        "user_id": "用户ID",
        "request_id": "上游请求ID",
        "audio_seconds": "音频时长(秒)",
        "status": "状态",
        "duration_ms": "耗时(ms)",
        "created_at": "录音时间",
    }
    column_searchable_list: ClassVar[list[str]] = ["user_id", "request_id"]
    column_sortable_list: ClassVar[list[str]] = [
        "id",
        "user_id",
        "audio_seconds",
        "duration_ms",
        "created_at",
    ]

    can_create = False
    can_edit = False
    can_delete = False


class AiUsageView(ModelView, model=AiUsage):
    """AI usage events: read-only ledger."""

    name = "AI 用量"
    name_plural = "AI 用量"
    icon = "fa-brain"
    category = "用量"

    column_list: ClassVar[list[str]] = [
        "id",
        "user_id",
        "purpose",
        "status",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "cache_hit_tokens",
        "cache_miss_tokens",
        "duration_ms",
        "created_at",
    ]
    column_labels: ClassVar[dict[str, str]] = {
        "id": "ID",
        "user_id": "用户ID",
        "purpose": "用途",
        "status": "状态",
        "prompt_tokens": "输入Token",
        "completion_tokens": "输出Token",
        "total_tokens": "总Token",
        "cache_hit_tokens": "缓存命中Token",
        "cache_miss_tokens": "缓存未命中Token",
        "duration_ms": "耗时(ms)",
        "created_at": "调用时间",
    }
    column_searchable_list: ClassVar[list[str]] = ["user_id"]
    column_sortable_list: ClassVar[list[str]] = [
        "id",
        "user_id",
        "total_tokens",
        "duration_ms",
        "created_at",
    ]

    can_create = False
    can_edit = False
    can_delete = False


class AdminView(ModelView, model=Admin):
    """Admin accounts: read-only. Created/disabled via the CLI script so that
    password hashing and session-invalidation stay in one place."""

    name = "管理员"
    name_plural = "管理员"
    icon = "fa-user-shield"
    category = "系统"

    column_list: ClassVar[list[str]] = [
        "id",
        "username",
        "status",
        "session_version",
        "created_at",
        "last_login_at",
    ]
    column_labels: ClassVar[dict[str, str]] = {
        "id": "ID",
        "username": "用户名",
        "status": "状态",
        "session_version": "会话版本",
        "created_at": "创建时间",
        "last_login_at": "最近登录",
    }
    column_searchable_list: ClassVar[list[str]] = ["username"]
    column_sortable_list: ClassVar[list[str]] = ["id", "username", "status", "last_login_at"]

    can_create = False
    can_edit = False
    can_delete = False


class AdminAuditLogView(ModelView, model=AdminAuditLog):
    name = "操作审计"
    name_plural = "操作审计"
    icon = "fa-clipboard-list"
    category = "系统"

    column_list: ClassVar[list[str]] = ["id", "username", "action", "target_type", "target_id", "created_at"]
    column_labels: ClassVar[dict[str, str]] = {
        "id": "ID",
        "username": "管理员",
        "action": "动作",
        "target_type": "对象类型",
        "target_id": "对象ID",
        "created_at": "时间",
    }
    column_sortable_list: ClassVar[list[str]] = ["id", "username", "action", "created_at"]

    can_create = False
    can_edit = False
    can_delete = False
