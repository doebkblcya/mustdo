from __future__ import annotations

import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, Query

from app.deps import current_user_invited, get_db
from app.schemas import TrashListResponse
from app.services.trash import list_trash


router = APIRouter(prefix="/api/trash", tags=["trash"])


@router.get("", response_model=TrashListResponse)
def get_trash(
    type: Literal["deleted", "overdue"] | None = Query(default=None),
    db: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user_invited),
):
    """垃圾桶列表。type 缺省时仅返回 deleted_count / overdue_count 摘要。"""
    return list_trash(db, int(user["id"]), type)
