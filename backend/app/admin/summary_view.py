"""Read-only usage-summary page for the admin console.

Uses SQLAdmin's ``@expose`` decorator, which (a) registers a custom non-model
route under ``/admin`` and (b) wraps it with ``login_required`` so it reuses
the same admin session authentication as the rest of the console.
"""

from __future__ import annotations

from typing import Any

from sqladmin import BaseView, expose

from app.db import get_connection
from app.services.summary import collect_usage_summary


class UsageSummaryView(BaseView):
    name = "用量汇总"
    category = "用量"
    icon = "fa-chart-bar"

    @expose("/usage/summary", identity="usage-summary")
    async def usage_summary(self, request: Any) -> Any:
        with get_connection() as db:
            rows = collect_usage_summary(db)
        return await self.templates.TemplateResponse(
            request,
            "admin/usage_summary.html",
            {"summary_rows": rows},
        )
