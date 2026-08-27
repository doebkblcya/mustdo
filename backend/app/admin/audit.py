"""Audit backend: record admin-console changes into ``admin_audit_logs``.

SQLAdmin calls this after create/update/delete on a ModelView. We capture the
acting admin from the session cookie and the change action/pk as a stable JSON
``detail`` blob.
"""

from __future__ import annotations

import json

from fastapi import Request
from sqladmin.audit import AuditBackend, AuditEntry

from app.db import get_connection
from app.time_utils import utcish_now_iso


class JsonAuditBackend(AuditBackend):
    async def log(self, entry: AuditEntry, request: Request) -> None:
        admin_id = request.session.get("admin_id")
        username = request.session.get("username")

        detail = None
        if entry.changes is not None:
            detail = json.dumps(entry.changes, ensure_ascii=False, default=str)

        with get_connection() as db:
            db.execute(
                """
                INSERT INTO admin_audit_logs
                    (admin_id, username, action, target_type, target_id, detail, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(admin_id) if admin_id is not None else None,
                    username,
                    entry.action,
                    entry.identity,
                    entry.pk,
                    detail,
                    utcish_now_iso(),
                ),
            )
            db.commit()
