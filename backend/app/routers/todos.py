from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, status

from app.deps import current_user, get_db
from app.errors import raise_api_error
from app.schemas import TodoListResponse, TodoPublic, TodoUpdateRequest
from app.services.todos import list_grouped_todos, soft_delete_todo, update_todo


router = APIRouter(prefix="/api/todos", tags=["todos"])


@router.get("", response_model=TodoListResponse)
def list_todos(
    db: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
):
    return list_grouped_todos(db, int(user["id"]))


@router.patch("/{todo_id}", response_model=TodoPublic)
def patch_todo(
    todo_id: int,
    payload: TodoUpdateRequest,
    db: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
):
    fields = payload.model_fields_set
    values: dict[str, object] = {}
    if "content" in fields:
        if payload.content is None:
            raise_api_error(status.HTTP_400_BAD_REQUEST, "content_required", "内容不能为空")
        values["content"] = payload.content
    if "due_date" in fields:
        if payload.due_date is None:
            raise_api_error(status.HTTP_400_BAD_REQUEST, "due_date_required", "日期不能为空")
        values["due_date"] = payload.due_date
    if "due_time" in fields:
        values["due_time"] = payload.due_time
    if "status" in fields:
        values["status"] = payload.status

    updated = update_todo(db, int(user["id"]), todo_id, values)
    if updated is None:
        raise_api_error(status.HTTP_404_NOT_FOUND, "todo_not_found", "待办不存在")
    return updated


@router.delete("/{todo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_todo(
    todo_id: int,
    db: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
) -> None:
    deleted = soft_delete_todo(db, int(user["id"]), todo_id)
    if not deleted:
        raise_api_error(status.HTTP_404_NOT_FOUND, "todo_not_found", "待办不存在")
    return None
