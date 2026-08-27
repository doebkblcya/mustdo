from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.time_utils import today_date


TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class UserPublic(BaseModel):
    id: int


class WechatLoginRequest(BaseModel):
    code: str = Field(min_length=1, max_length=256)


class InviteRedeemRequest(BaseModel):
    code: str = Field(min_length=1, max_length=128)


class AuthTokenResponse(BaseModel):
    user: UserPublic
    token: str
    token_type: Literal["bearer"] = "bearer"
    needs_invite: bool


class ReminderPublic(BaseModel):
    remind_at: str
    status: Literal["pending", "sent", "failed", "cancelled"]
    error_code: str | None = None


class ReminderUpsertRequest(BaseModel):
    remind_at: datetime


class ReminderResponse(BaseModel):
    reminder: ReminderPublic


class TodoPublic(BaseModel):
    id: int
    content: str
    due_date: date
    due_time: str | None
    status: Literal["pending", "done"]
    pinned: bool
    created_at: str
    updated_at: str
    reminder: ReminderPublic | None = None


class TodoGroups(BaseModel):
    today: list[TodoPublic]
    tomorrow: list[TodoPublic]
    upcoming: list[TodoPublic]


class TodoListResponse(BaseModel):
    today_date: date
    tomorrow_date: date
    groups: TodoGroups


class TrashItem(TodoPublic):
    deleted_at: str | None = None


class TrashListResponse(BaseModel):
    deleted_count: int
    overdue_count: int
    items: list[TrashItem]


class TodoUpdateRequest(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=200)
    due_date: date | None = None
    due_time: str | None = None
    status: Literal["pending", "done"] | None = None
    pinned: bool | None = None
    # 恢复：软删项可用 deleted_at=None 清除删除标记（v2-02 提醒落地前无提醒字段可清）
    # 只允许 null：非 null 值可伪造删除时间、绕过 DELETE 与 7 天清理窗口
    deleted_at: str | None = None

    @field_validator("deleted_at")
    @classmethod
    def validate_deleted_at(cls, value: str | None) -> str | None:
        if value is not None:
            raise ValueError("deleted_at must be null to restore")
        return value

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.strip().split())
        if not cleaned:
            raise ValueError("content is required")
        return cleaned

    @field_validator("due_time")
    @classmethod
    def validate_due_time(cls, value: str | None) -> str | None:
        if value in {"", None}:
            return None
        if not TIME_RE.fullmatch(value):
            raise ValueError("due_time must be HH:MM")
        return value


class TranscriptionResponse(BaseModel):
    transcript: str


class TodoParseRequest(BaseModel):
    transcript: str = Field(min_length=1, max_length=4000)
    source: Literal["voice", "text"] = "voice"

    @field_validator("transcript")
    @classmethod
    def normalize_transcript(cls, value: str) -> str:
        cleaned = " ".join(value.strip().split())
        if not cleaned:
            raise ValueError("transcript is required")
        return cleaned


class ParsedItemOut(BaseModel):
    content: str
    due_date: date
    due_time: str | None


class TodoParseResponse(BaseModel):
    transcript: str
    items: list[ParsedItemOut]
    message: str | None = None


class BatchCreateItem(BaseModel):
    content: str = Field(min_length=1, max_length=200)
    due_date: date
    due_time: str | None = None

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        cleaned = " ".join(value.strip().split())
        if not cleaned:
            raise ValueError("content is required")
        return cleaned

    @field_validator("due_date")
    @classmethod
    def normalize_due_date(cls, value: date) -> date:
        return max(value, today_date())

    @field_validator("due_time")
    @classmethod
    def validate_due_time(cls, value: str | None) -> str | None:
        if value in {"", None}:
            return None
        if not TIME_RE.fullmatch(value):
            raise ValueError("due_time must be HH:MM")
        return value


class BatchCreateRequest(BaseModel):
    items: list[BatchCreateItem] = Field(min_length=1, max_length=20)


class BatchCreateResponse(BaseModel):
    items: list[TodoPublic]


class OrganizeItem(BaseModel):
    id: int
    content: str = Field(min_length=1, max_length=200)
    due_time: str | None = None

    @field_validator("due_time")
    @classmethod
    def validate_due_time(cls, value: str | None) -> str | None:
        if value in {"", None}:
            return None
        if not TIME_RE.fullmatch(value):
            raise ValueError("due_time must be HH:MM")
        return value


class OrganizeRequest(BaseModel):
    view: Literal["today", "tomorrow"] = "today"
    items: list[OrganizeItem] = Field(min_length=1, max_length=200)


class OrganizeGroup(BaseModel):
    name: str = Field(min_length=1, max_length=20)
    todo_ids: list[int]


class OrganizeResponse(BaseModel):
    view: Literal["today", "tomorrow"]
    groups: list[OrganizeGroup]
