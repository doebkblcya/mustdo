from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError

from app.admin import mount_admin
from app.db import cleanup_sessions, init_db
from app.errors import http_exception_handler, validation_exception_handler
from app.routers import auth, invites, reminders, todos, trash, voice
from app.services.deepseek import close_deepseek_client
from app.services.scheduler import reminder_loop
from app.services.wechat import close_wechat_client


def create_app() -> FastAPI:

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        init_db()
        cleanup_sessions()
        # 单 worker 部署（WORKERS=1）：进程内调度器是唯一分发实例，
        # 重启后立即补扫所有到期的 pending 提醒。
        reminder_task = asyncio.create_task(reminder_loop())
        yield
        reminder_task.cancel()
        try:
            await reminder_task
        except asyncio.CancelledError:
            pass
        await close_deepseek_client()
        await close_wechat_client()

    app = FastAPI(title="Mustdo", version="0.1.0", lifespan=lifespan)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth.router)
    app.include_router(invites.router)
    app.include_router(todos.router)
    app.include_router(reminders.router)
    app.include_router(trash.router)
    app.include_router(voice.router)

    # Admin console mounted onto the same app at /admin.
    mount_admin(app)

    return app


app = create_app()
