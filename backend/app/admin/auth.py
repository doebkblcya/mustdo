"""Admin authentication backend for SQLAdmin.

Uses SQLAdmin's ``AuthenticationBackend`` (which wires a Starlette
``SessionMiddleware`` signed cookie). We store ``admin_id``,
``session_version`` and ``nonce`` in the session; ``session_version`` lives in
the DB and is bumped on password change / disable, which invalidates every
existing session for that admin at once.
"""

from __future__ import annotations

from fastapi import Request
from sqladmin.authentication import AuthenticationBackend

from app.admin_security import (
    admin_session_payload,
    generate_admin_session_nonce,
    verify_password,
)
from app.config import get_settings
from app.db import get_connection
from app.time_utils import utcish_now_iso


class AdminAuth(AuthenticationBackend):
    def __init__(self) -> None:
        super().__init__(secret_key=_admin_secret())

    async def login(self, request: Request) -> bool:
        form = await request.form()
        username = str(form.get("username", "")).strip()
        password = str(form.get("password", ""))
        norm = username.lower()
        with get_connection() as db:
            row = db.execute(
                "SELECT * FROM admins WHERE username_normalized = ?",
                (norm,),
            ).fetchone()
            if row is None or row["status"] != "active":
                return False
            if not verify_password(password, row["password_hash"]):
                return False
            request.session.update(
                admin_session_payload(
                    int(row["id"]),
                    str(row["username"]),
                    int(row["session_version"]),
                    generate_admin_session_nonce(),
                )
            )
            db.execute(
                "UPDATE admins SET last_login_at = ? WHERE id = ?",
                (utcish_now_iso(), int(row["id"])),
            )
            db.commit()
        return True

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        admin_id = request.session.get("admin_id")
        session_version = request.session.get("session_version")
        nonce = request.session.get("nonce")
        if not admin_id or session_version is None or not nonce:
            return False
        with get_connection() as db:
            row = db.execute(
                "SELECT id, status, session_version FROM admins WHERE id = ?",
                (int(admin_id),),
            ).fetchone()
        if row is None or row["status"] != "active":
            return False
        # Bumping session_version (password change / disable) invalidates old cookies.
        return int(row["session_version"]) == int(session_version)


def _admin_secret() -> str:
    return get_settings().secret_key
