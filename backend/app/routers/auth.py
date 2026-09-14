from __future__ import annotations

import sqlite3
from datetime import timedelta

from fastapi import APIRouter, Depends, status

from app.config import get_settings
from app.deps import current_user, get_db
from app.errors import raise_api_error
from app.schemas import (
    AiQuotaPublic,
    AsrQuotaPublic,
    AuthTokenResponse,
    QuotaPublicResponse,
    UserPublic,
    WechatLoginRequest,
)
from app.security import generate_session_token, hash_session_token
from app.services.quota import (
    ai_used_tokens_total,
    asr_used_seconds_total,
    create_default_quota,
    get_quota,
)
from app.services.wechat import WechatLoginError, exchange_code_for_openid
from app.time_utils import now_shanghai, utcish_now_iso

router = APIRouter(prefix="/api", tags=["auth"])


def _create_session(db: sqlite3.Connection, user_id: int) -> str:
    settings = get_settings()
    token = generate_session_token()
    now = now_shanghai()
    expires_at = now + timedelta(days=settings.session_days)
    db.execute(
        """
        INSERT INTO sessions (user_id, token_hash, created_at, expires_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            user_id,
            hash_session_token(token),
            now.isoformat(timespec="seconds"),
            expires_at.isoformat(timespec="seconds"),
        ),
    )
    return token


@router.post("/auth/wechat", response_model=AuthTokenResponse)
async def wechat_login(
    payload: WechatLoginRequest,
    db: sqlite3.Connection = Depends(get_db),
):
    try:
        openid = await exchange_code_for_openid(payload.code)
    except WechatLoginError as exc:
        raise_api_error(exc.http_status, exc.code, exc.message)

    now = utcish_now_iso()
    existing = db.execute(
        "SELECT id, status FROM users WHERE wechat_openid = ?",
        (openid,),
    ).fetchone()

    if existing is not None and existing["status"] != "active":
        raise_api_error(status.HTTP_403_FORBIDDEN, "account_disabled", "账号当前不可用")

    try:
        db.execute("BEGIN IMMEDIATE")
        if existing is None:
            cursor = db.execute(
                """
                INSERT INTO users (wechat_openid, status, created_at, updated_at, last_login_at)
                VALUES (?, 'active', ?, ?, ?)
                """,
                (openid, now, now, now),
            )
            user_id = int(cursor.lastrowid)
            create_default_quota(db, user_id)
        else:
            user_id = int(existing["id"])
            db.execute(
                "UPDATE users SET last_login_at = ? WHERE id = ?",
                (now, user_id),
            )
            create_default_quota(db, user_id)
        token = _create_session(db, user_id)
        db.execute("COMMIT")
    except sqlite3.Error:
        db.execute("ROLLBACK")
        raise_api_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "wechat_login_failed",
            "微信登录失败，请重试",
        )

    return AuthTokenResponse(
        user=UserPublic(id=user_id),
        token=token,
    )


@router.get("/me", response_model=UserPublic)
def me(user: sqlite3.Row = Depends(current_user)):
    return UserPublic(id=int(user["id"]))


@router.get("/me/quota", response_model=QuotaPublicResponse)
def my_quota(
    db: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
):
    user_id = int(user["id"])
    quota = get_quota(db, user_id)
    asr_limit = float(quota["asr_total_seconds"] or 0)
    ai_limit = int(quota["ai_total_tokens"] or 0)
    asr_used = asr_used_seconds_total(db, user_id)
    ai_used = ai_used_tokens_total(db, user_id)
    return QuotaPublicResponse(
        asr=AsrQuotaPublic(
            enabled=bool(quota["asr_enabled"]),
            total_seconds=asr_limit,
            used_seconds=asr_used,
            remaining_seconds=max(0.0, asr_limit - asr_used) if asr_limit > 0 else None,
            unlimited=asr_limit <= 0,
        ),
        ai=AiQuotaPublic(
            enabled=bool(quota["ai_enabled"]),
            total_tokens=ai_limit,
            used_tokens=ai_used,
            remaining_tokens=max(0, ai_limit - ai_used) if ai_limit > 0 else None,
            unlimited=ai_limit <= 0,
        ),
    )
