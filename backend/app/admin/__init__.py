"""Mount the SQLAdmin console onto the existing FastAPI app at ``/admin``.

This is the "hybrid" seam: the console reads/writes the app's SQLite DB through
SQLAlchemy, while the business API keeps using native sqlite3. Both engines
point at the same file with matching pragmas.
"""

from __future__ import annotations

from fastapi import FastAPI
from sqladmin import Admin

from app.admin.audit import JsonAuditBackend
from app.admin.auth import AdminAuth
from app.admin.engine import create_admin_engine
from app.admin.views import (
    AdminAuditLogView,
    AdminView,
    AiUsageView,
    AsrUsageView,
    UserQuotaView,
    UserView,
)


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
    )

    for view in (
        UserView,
        UserQuotaView,
        AsrUsageView,
        AiUsageView,
        AdminView,
        AdminAuditLogView,
    ):
        admin.add_view(view)

    return admin
