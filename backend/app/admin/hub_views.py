"""Human-oriented admin pages layered on top of the raw SQLAdmin views."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request
from sqladmin import BaseView, expose

from app.db import get_connection
from app.services.admin_dashboard import (
    collect_dashboard,
    get_user_detail,
    list_diagnostics,
    list_users,
    normalize_days,
)


def _positive_page(raw: str | None) -> int:
    return max(1, int(raw)) if raw and raw.isdigit() else 1


class UsersHubView(BaseView):
    name = "用户"
    icon = "fa-solid fa-users"

    @expose("/users", identity="users-hub")
    async def users(self, request: Request) -> Any:
        qp = request.query_params
        with get_connection() as db:
            result = list_users(
                db,
                query=qp.get("q", ""),
                status=qp.get("status", "all"),
                usage=qp.get("usage", "all"),
                sort=qp.get("sort", "active"),
                page=_positive_page(qp.get("page")),
            )
        return await self.templates.TemplateResponse(
            request,
            "admin/users.html",
            {"result": result, "title": "用户管理"},
        )


class UserDetailView(BaseView):
    name = "用户详情"

    def is_visible(self, request: Request) -> bool:
        return False

    @expose("/users/{user_id:int}", identity="user-detail")
    async def detail(self, request: Request) -> Any:
        user_id = int(request.path_params["user_id"])
        days = normalize_days(request.query_params.get("days"), default=7)
        with get_connection() as db:
            detail = get_user_detail(db, user_id, days)
        if detail is None:
            raise HTTPException(status_code=404, detail="用户不存在")
        return await self.templates.TemplateResponse(
            request,
            "admin/user_detail.html",
            {"detail": detail, "title": f"用户 #{user_id}"},
        )


class UsageCenterView(BaseView):
    name = "用量"
    icon = "fa-solid fa-chart-line"

    @expose("/usage", identity="usage-center")
    async def usage(self, request: Request) -> Any:
        days = normalize_days(request.query_params.get("days"), default=7)
        with get_connection() as db:
            dashboard = collect_dashboard(db, days)
        return await self.templates.TemplateResponse(
            request,
            "admin/usage_center.html",
            {"dashboard": dashboard, "title": "用量中心"},
        )


class DiagnosticsView(BaseView):
    name = "诊断"
    icon = "fa-solid fa-stethoscope"

    @expose("/diagnostics", identity="diagnostics")
    async def diagnostics(self, request: Request) -> Any:
        qp = request.query_params
        with get_connection() as db:
            result = list_diagnostics(
                db,
                kind=qp.get("kind", "reminders"),
                query=qp.get("q", ""),
                status=qp.get("status", "all"),
                page=_positive_page(qp.get("page")),
            )
        return await self.templates.TemplateResponse(
            request,
            "admin/diagnostics.html",
            {"result": result, "title": "诊断中心"},
        )
