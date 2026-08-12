from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError

from app.db import cleanup_sessions, init_db
from app.errors import http_exception_handler, validation_exception_handler
from app.routers import auth, todos, voice
from app.services.deepseek import close_deepseek_client


def create_app() -> FastAPI:

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        init_db()
        cleanup_sessions()
        yield
        await close_deepseek_client()

    app = FastAPI(title="Mustdo", version="0.1.0", lifespan=lifespan)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth.router)
    app.include_router(todos.router)
    app.include_router(voice.router)

    return app


app = create_app()
