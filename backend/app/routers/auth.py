from __future__ import annotations

import sqlite3
from datetime import timedelta

from fastapi import APIRouter, Depends, Header, status

from app.config import get_settings
from app.deps import bearer_token_from_authorization, current_user, get_db
from app.errors import raise_api_error
from app.schemas import AuthTokenResponse, UserPublic, WechatLoginRequest
from app.security import generate_session_token, hash_session_token
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
        "SELECT id, status, invite_redeemed_at FROM users WHERE wechat_openid = ?",
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
            invite_redeemed = None
        else:
            user_id = int(existing["id"])
            invite_redeemed = existing["invite_redeemed_at"]
            db.execute(
                "UPDATE users SET last_login_at = ? WHERE id = ?",
                (now, user_id),
            )
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
        needs_invite=invite_redeemed is None,
    )


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    db: sqlite3.Connection = Depends(get_db),
    authorization: str | None = Header(default=None),
):
    token = bearer_token_from_authorization(authorization)
    if token:
        db.execute(
            "UPDATE sessions SET revoked_at = ? WHERE token_hash = ?",
            (utcish_now_iso(), hash_session_token(token)),
        )
        db.commit()


@router.get("/me", response_model=UserPublic)
def me(user: sqlite3.Row = Depends(current_user)):
    return UserPublic(id=int(user["id"]))
