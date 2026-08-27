"""Create invite codes from the admin console.

A plain ``BaseView`` with a GET/POST form: the admin picks a type + label, we
generate a code, store only its HMAC hash (never the plaintext), and show the
plaintext exactly once at creation. The business redeem flow
(``services/invite_gate``) is untouched — it keeps matching against the hash.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import Request
from sqladmin import BaseView, expose

from app.db import get_connection
from app.security import generate_invite_code, hash_invite_code
from app.time_utils import utcish_now_iso

_INVITE_TYPES = ("single", "multi")


class InviteCreateView(BaseView):
    name = "新建邀请码"
    category = "邀请码"
    icon = "fa-plus"

    # NOTE: the path must not collide with SQLAdmin's generic ModelView
    # wildcard routes (/{identity}/list|create|edit|delete|...). "/invites/new"
    # is the "new" segment so it falls through to this BaseView rather than
    # being captured as identity="invites" on /{identity}/create.
    @expose("/invites/new", identity="invite-create", methods=["GET", "POST"])
    async def create(self, request: Request) -> Any:
        errors: list[str] = []
        invite_type = "single"
        label = ""
        created = None

        if request.method == "POST":
            form = await request.form()
            invite_type = str(form.get("type", "single"))
            label = str(form.get("label", "")).strip()
            if invite_type not in _INVITE_TYPES:
                errors.append("类型无效")
            else:
                created = _create_invite(invite_type, label or None, request)

        return await self.templates.TemplateResponse(
            request,
            "admin/invite_create.html",
            {
                "invite_type": invite_type,
                "label": label,
                "created": created,
                "errors": errors,
            },
        )


def _create_invite(invite_type: str, label: str | None, request: Request) -> str:
    """Generate a code, store its hash, and write an audit row.

    Returns the plaintext code — the only time it is ever shown.
    """
    code = generate_invite_code(invite_type)
    now = utcish_now_iso()
    with get_connection() as db:
        cursor = db.execute(
            """
            INSERT INTO invite_codes (code_hash, type, status, label, created_at)
            VALUES (?, ?, 'active', ?, ?)
            """,
            (hash_invite_code(code), invite_type, label, now),
        )
        _log_audit(db, request, "create", cursor.lastrowid, invite_type, label)
        db.commit()
    return code


def _log_audit(
    db,
    request: Request,
    action: str,
    invite_id: int,
    invite_type: str,
    label: str | None,
) -> None:
    """Record the create action without leaking the code into the audit log."""
    detail = json.dumps({"type": invite_type, "label": label}, ensure_ascii=False, default=str)
    db.execute(
        """
        INSERT INTO admin_audit_logs
            (admin_id, username, action, target_type, target_id, detail, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(request.session["admin_id"]) if request.session.get("admin_id") else None,
            request.session.get("username"),
            action,
            "invite_codes",
            str(invite_id),
            detail,
            utcish_now_iso(),
        ),
    )
