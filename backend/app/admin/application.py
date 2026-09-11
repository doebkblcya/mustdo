"""SQLAdmin application subclass with a useful authenticated home page."""

from __future__ import annotations

from fastapi import Request
from sqladmin import Admin
from sqladmin.authentication import login_required

from app.db import get_connection
from app.services.admin_dashboard import collect_dashboard, normalize_days


class MustdoAdmin(Admin):
    @login_required
    async def index(self, request: Request):
        days = normalize_days(request.query_params.get("days"), default=7)
        with get_connection() as db:
            dashboard = collect_dashboard(db, days)
        return await self.templates.TemplateResponse(
            request,
            "admin/dashboard.html",
            {"dashboard": dashboard, "title": "运营概览"},
        )
