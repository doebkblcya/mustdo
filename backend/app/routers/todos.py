from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.deps import current_user, get_db
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
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="内容不能为空")
        values["content"] = payload.content
    if "due_date" in fields:
        if payload.due_date is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="日期不能为空")
        values["due_date"] = payload.due_date
    if "due_time" in fields:
        values["due_time"] = payload.due_time
    if "status" in fields:
        values["status"] = payload.status

    updated = update_todo(db, int(user["id"]), todo_id, values)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="待办不存在")
    return updated


@router.delete("/{todo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_todo(
    todo_id: int,
    response: Response,
    db: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
):
    deleted = soft_delete_todo(db, int(user["id"]), todo_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="待办不存在")
    return response
