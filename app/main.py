from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.analyses import router as analyses_router
from app.db.session import init_db


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    init_db()
    yield


app = FastAPI(title="Todo Analyzer", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(analyses_router, prefix="/api/v1")
