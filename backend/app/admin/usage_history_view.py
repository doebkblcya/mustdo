"""Per-user historical ASR/AI usage page for the admin console.

A GET-only ``BaseView``: pick a user + time window, see aggregated ASR/AI
stats and a per-day breakdown. Aggregation runs over the native sqlite3 path
(``collect_user_usage``), consistent with the rest of the metering views.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from sqladmin import BaseView, expose

from app.db import get_connection
from app.services.usage_history import collect_user_usage

_PRESETS = (1, 7, 30, 0)


class UserUsageView(BaseView):
    name = "用户用量"
    category = "用量"
    icon = "fa-chart-line"

    @expose("/usage/user", identity="usage-user")
    async def usage_user(self, request: Request) -> Any:
        qp = request.query_params
        raw_user = qp.get("user_id")
        raw_days = qp.get("days")
        user_id = int(raw_user) if raw_user and raw_user.isdigit() else None
        days = int(raw_days) if raw_days and raw_days.isdigit() else 30
        if days not in _PRESETS:
            days = 30

        with get_connection() as db:
            users = db.execute(
                "SELECT id, wechat_openid FROM users ORDER BY id"
            ).fetchall()
            result = collect_user_usage(db, user_id, days) if user_id is not None else None

        return await self.templates.TemplateResponse(
            request,
            "admin/usage_user.html",
            {"users": users, "user_id": user_id, "days": days, "result": result},
        )
