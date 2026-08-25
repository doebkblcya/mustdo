from __future__ import annotations

import sqlite3

from fastapi import status

from app.errors import raise_api_error
from app.security import hash_invite_code, normalize_invite_code
from app.time_utils import utcish_now_iso


def redeem_invite(db: sqlite3.Connection, user_id: int, raw_code: str) -> None:
    """Bind an active invite code to a user.

    This is the redeem step of the invite gate. It marks the invite code as
    used (single -> redeemed, multi -> stays active) and stamps the user's
    ``invite_redeemed_at`` so later logins skip the gate. Drop this module at
    public launch.
    """
    code_hash = hash_invite_code(raw_code)
    now = utcish_now_iso()

    existing = db.execute(
        "SELECT invite_redeemed_at FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if existing is None:
        raise_api_error(status.HTTP_404_NOT_FOUND, "user_not_found", "用户不存在")
    if existing["invite_redeemed_at"] is not None:
        raise_api_error(status.HTTP_409_CONFLICT, "already_redeemed", "已绑定邀请码")

    try:
        db.execute("BEGIN IMMEDIATE")
        invite = db.execute(
            "SELECT * FROM invite_codes WHERE code_hash = ? AND status = 'active'",
            (code_hash,),
        ).fetchone()
        if invite is None:
            db.execute("ROLLBACK")
            raise_api_error(status.HTTP_400_BAD_REQUEST, "invalid_invite_code", "邀请码无效")

        if invite["type"] == "single":
            db.execute(
                """
                UPDATE invite_codes
                SET status = 'redeemed', used_at = ?, used_by_user_id = ?
                WHERE id = ?
                """,
                (now, user_id, invite["id"]),
            )
        else:
            db.execute(
                """
                UPDATE invite_codes
                SET used_at = ?, used_by_user_id = ?
                WHERE id = ?
                """,
                (now, user_id, invite["id"]),
            )
        db.execute(
            "UPDATE users SET invite_redeemed_at = ?, updated_at = ? WHERE id = ?",
            (now, now, user_id),
        )
        db.execute("COMMIT")
    except sqlite3.Error:
        db.execute("ROLLBACK")
        raise_api_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "redeem_failed",
            "绑定邀请码失败",
        )
