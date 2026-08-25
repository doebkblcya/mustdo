from __future__ import annotations

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator


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


class TodoPublic(BaseModel):
    id: int
    content: str
    due_date: date
    due_time: str | None
    status: Literal["pending", "done"]
    pinned: bool
    created_at: str
    updated_at: str


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
    deleted_at: str | None = None

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


class AiCreateRequest(BaseModel):
    transcript: str = Field(min_length=1, max_length=4000)
    # 输入来源：voice=语音转写（默认，兼容旧客户端），text=键盘输入
    source: Literal["voice", "text"] = "voice"

    @field_validator("transcript")
    @classmethod
    def normalize_transcript(cls, value: str) -> str:
        cleaned = " ".join(value.strip().split())
        if not cleaned:
            raise ValueError("transcript is required")
        return cleaned


class AiCreateResponse(BaseModel):
    transcript: str
    items: list[TodoPublic]
    message: str | None = None


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
