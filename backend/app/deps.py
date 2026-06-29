from __future__ import annotations

import sqlite3
from collections.abc import Generator

from fastapi import Cookie, Depends, status

from app.config import get_settings
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


def current_user(
    db: sqlite3.Connection = Depends(get_db),
    session_token: str | None = Cookie(default=None, alias=get_settings().session_cookie_name),
) -> sqlite3.Row:
    if not session_token:
        raise_api_error(status.HTTP_401_UNAUTHORIZED, "unauthorized", "请先登录")

    token_hash = hash_session_token(session_token)
    now = utcish_now_iso()
    row = db.execute(
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
    if row is None:
        raise_api_error(status.HTTP_401_UNAUTHORIZED, "unauthorized", "请先登录")
    return row
