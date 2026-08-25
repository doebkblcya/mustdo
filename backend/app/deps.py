from __future__ import annotations

import sqlite3
from collections.abc import Generator

from fastapi import Depends, Header, status

from app.db import get_connection
from app.errors import raise_api_error
from app.security import hash_session_token
from app.time_utils import utcish_now_iso


def get_db() -> Generator[sqlite3.Connection, None, None]:
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def bearer_token_from_authorization(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.strip().partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def user_from_session_token(db: sqlite3.Connection, session_token: str | None) -> sqlite3.Row | None:
    if not session_token:
        return None
    token_hash = hash_session_token(session_token)
    now = utcish_now_iso()
    return db.execute(
        """
        SELECT users.*
        FROM sessions
        JOIN users ON users.id = sessions.user_id
        WHERE sessions.token_hash = ?
          AND sessions.revoked_at IS NULL
          AND sessions.expires_at > ?
          AND users.status = 'active'
        """,
        (token_hash, now),
    ).fetchone()


def current_user(
    db: sqlite3.Connection = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> sqlite3.Row:
    token = bearer_token_from_authorization(authorization)
    row = user_from_session_token(db, token)
    if row is None:
        raise_api_error(status.HTTP_401_UNAUTHORIZED, "unauthorized", "请先登录")
    return row


def current_user_invited(
    user: sqlite3.Row = Depends(current_user),
) -> sqlite3.Row:
    """Authentication + invite gate.

    Business endpoints require a redeemed invite code during the closed beta.
    Remove this wrapper (and switch endpoints back to ``current_user``) when the
    invite module is dropped at public launch.
    """
    if user["invite_redeemed_at"] is None:
        raise_api_error(status.HTTP_403_FORBIDDEN, "invite_required", "请先填写邀请码")
    return user
