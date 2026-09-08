from __future__ import annotations

import asyncio
import logging
from time import perf_counter
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


logger = logging.getLogger("uvicorn.error")


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

    @app.middleware("http")
    async def log_voice_request_timing(request, call_next):
        if request.url.path != "/api/voice/transcriptions":
            return await call_next(request)
        started_at = perf_counter()
        response = await call_next(request)
        logger.info(
            "voice_http_done trace_id=%s request_ms=%s request_bytes=%s status_code=%s",
            request.headers.get("x-trace-id", "-"),
            round((perf_counter() - started_at) * 1000),
            request.headers.get("content-length", "-"),
            response.status_code,
        )
        return response
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
