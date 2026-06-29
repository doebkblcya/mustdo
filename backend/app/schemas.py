from __future__ import annotations

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator


TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class UserPublic(BaseModel):
    id: int
    username: str


class RegisterRequest(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=128)
    invite_code: str = Field(max_length=128)


class LoginRequest(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=128)


class AuthResponse(BaseModel):
    user: UserPublic


class AuthTokenResponse(BaseModel):
    user: UserPublic
    token: str
    token_type: Literal["bearer"] = "bearer"


class TodoPublic(BaseModel):
    id: int
    content: str
    due_date: date
    due_time: str | None
    status: Literal["pending", "done"]
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


class TodoUpdateRequest(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=200)
    due_date: date | None = None
    due_time: str | None = None
    status: Literal["pending", "done"] | None = None

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
