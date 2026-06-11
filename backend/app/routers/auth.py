from __future__ import annotations

import sqlite3
from datetime import timedelta

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status

from app.config import get_settings
from app.deps import current_user, get_db
from app.schemas import AuthResponse, LoginRequest, RegisterRequest, UserPublic
from app.security import (
    generate_session_token,
    hash_invite_code,
    hash_password,
    hash_session_token,
    normalize_username,
    validate_password,
    validate_username,
    verify_password,
)
from app.time_utils import now_shanghai, utcish_now_iso


router = APIRouter(prefix="/api", tags=["auth"])


def _set_session_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_days * 24 * 60 * 60,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )


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


@router.post("/auth/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, response: Response, db: sqlite3.Connection = Depends(get_db)):
    try:
        username = validate_username(payload.username)
        validate_password(payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    username_normalized = normalize_username(username)
    invite_hash = hash_invite_code(payload.invite_code)
    now = utcish_now_iso()

    try:
        db.execute("BEGIN IMMEDIATE")
        invite = db.execute(
            "SELECT * FROM invite_codes WHERE code_hash = ? AND status = 'active'",
            (invite_hash,),
        ).fetchone()
        if invite is None:
            db.execute("ROLLBACK")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="邀请码无效")

        existing_user = db.execute(
            "SELECT id FROM users WHERE username_normalized = ?",
            (username_normalized,),
        ).fetchone()
        if existing_user is not None:
            db.execute("ROLLBACK")
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名已存在")

        cursor = db.execute(
            """
            INSERT INTO users (
                username, username_normalized, password_hash, status, created_at, updated_at
            )
            VALUES (?, ?, ?, 'active', ?, ?)
            """,
            (username, username_normalized, hash_password(payload.password), now, now),
        )
        user_id = int(cursor.lastrowid)
        db.execute(
            """
            UPDATE invite_codes
            SET status = 'redeemed', used_at = ?, used_by_user_id = ?
            WHERE id = ?
            """,
            (now, user_id, invite["id"]),
        )
        token = _create_session(db, user_id)
        db.execute("COMMIT")
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        db.execute("ROLLBACK")
        raise HTTPException(status_code=500, detail="注册失败") from exc

    _set_session_cookie(response, token)
    return AuthResponse(user=UserPublic(id=user_id, username=username))


@router.post("/auth/login", response_model=AuthResponse)
def login(payload: LoginRequest, response: Response, db: sqlite3.Connection = Depends(get_db)):
    user = db.execute(
        """
        SELECT * FROM users
        WHERE username_normalized = ? AND status = 'active'
        """,
        (normalize_username(payload.username),),
    ).fetchone()
    if user is None or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")

    token = _create_session(db, int(user["id"]))
    db.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (utcish_now_iso(), user["id"]))
    db.commit()
    _set_session_cookie(response, token)
    return AuthResponse(user=UserPublic(id=user["id"], username=user["username"]))


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    db: sqlite3.Connection = Depends(get_db),
    session_token: str | None = Cookie(default=None, alias=get_settings().session_cookie_name),
):
    settings = get_settings()
    if session_token:
        db.execute(
            "UPDATE sessions SET revoked_at = ? WHERE token_hash = ?",
            (utcish_now_iso(), hash_session_token(session_token)),
        )
        db.commit()
    response.delete_cookie(key=settings.session_cookie_name, path="/")


@router.get("/me", response_model=UserPublic)
def me(user: sqlite3.Row = Depends(current_user)):
    return UserPublic(id=user["id"], username=user["username"])
