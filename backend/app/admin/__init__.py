"""Mount the SQLAdmin console onto the existing FastAPI app at ``/admin``.

This is the "hybrid" seam: the console reads/writes the app's SQLite DB through
SQLAlchemy, while the business API keeps using native sqlite3. Both engines
point at the same file with matching pragmas.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from sqladmin import Admin

from app.admin.audit import JsonAuditBackend
from app.admin.auth import AdminAuth
from app.admin.engine import create_admin_engine
from app.admin.invite_create_view import InviteCreateView
from app.admin.summary_view import UsageSummaryView
from app.admin.usage_history_view import UserUsageView
from app.admin.views import (
    AdminAuditLogView,
    AdminView,
    AiUsageView,
    AsrUsageView,
    InviteCodeView,
    TodoReminderView,
    TodoView,
    UserQuotaView,
    UserView,
)

# Absolute path to the console's custom templates (independent of CWD so it
# doesn't break when uvicorn is launched from elsewhere). File is under
# backend/templates/, so from app/admin/__init__.py that's parents[2].
_TEMPLATES_DIR = str(Path(__file__).resolve().parents[2] / "templates")


def mount_admin(app: FastAPI) -> None:
    """Attach the admin console at ``/admin``.

    ``create_admin_engine`` builds the engine lazily at this point (it only
    opens a connection on first use) so calling this during ``create_app`` is
    safe before the lifespan has run ``init_db``.
    """
    engine, session_maker = create_admin_engine()
    _ = engine  # kept alive for the session_maker's bind; session_maker is what SQLAdmin uses.

    admin = Admin(
        app,
        session_maker=session_maker,
        authentication_backend=AdminAuth(),
        audit_backend=JsonAuditBackend(),
        base_url="/admin",
        title="Mustdo 管理后台",
        logo_url=None,
        templates_dir=_TEMPLATES_DIR,
    )

    for view in (
        UserView,
        UserQuotaView,
        TodoView,
        AsrUsageView,
        AiUsageView,
        UsageSummaryView,
        UserUsageView,
        InviteCodeView,
        InviteCreateView,
        TodoReminderView,
        AdminView,
        AdminAuditLogView,
    ):
        admin.add_view(view)

    return admin
