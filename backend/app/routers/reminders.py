from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, status

from app.deps import current_user_invited, get_db
from app.schemas import ReminderResponse, ReminderUpsertRequest
from app.services.reminders import cancel_reminder, normalize_remind_at, upsert_reminder

router = APIRouter(prefix="/api/todos", tags=["reminders"])


@router.put("/{todo_id}/reminder", response_model=ReminderResponse)
def put_reminder(
    todo_id: int,
    payload: ReminderUpsertRequest,
    db: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user_invited),
):
    """创建或更新待办提醒（todo 维度 upsert，同一时刻仅一个有效提醒）。"""
    remind_at = normalize_remind_at(payload.remind_at)
    reminder = upsert_reminder(db, int(user["id"]), todo_id, remind_at)
    return ReminderResponse(reminder=reminder)


@router.delete("/{todo_id}/reminder", status_code=status.HTTP_204_NO_CONTENT)
def delete_reminder(
    todo_id: int,
    db: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user_invited),
) -> None:
    """取消待办提醒（pending/failed → cancelled）。"""
    cancel_reminder(db, int(user["id"]), todo_id)
