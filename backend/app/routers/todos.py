from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, status

from app.deps import current_user_invited, get_db
from app.errors import raise_api_error
from app.schemas import (
    OrganizeRequest,
    OrganizeResponse,
    TodoListResponse,
    TodoPublic,
    TodoUpdateRequest,
)
from app.services.deepseek import DeepSeekParseError, organize_todos_with_deepseek
from app.services.todos import list_grouped_todos, soft_delete_todo, update_todo


router = APIRouter(prefix="/api/todos", tags=["todos"])


@router.get("", response_model=TodoListResponse)
def list_todos(
    db: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user_invited),
):
    return list_grouped_todos(db, int(user["id"]))


@router.post("/organize", response_model=OrganizeResponse)
async def organize_todos(
    payload: OrganizeRequest,
    db: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user_invited),
):
    user_id = int(user["id"])

    # 归属校验：请求中的待办必须全部属于当前用户且未删除
    unique_ids = list(dict.fromkeys(item.id for item in payload.items))
    placeholders = ",".join("?" for _ in unique_ids)
    rows = db.execute(
        f"""
        SELECT id FROM todos
        WHERE user_id = ? AND deleted_at IS NULL AND id IN ({placeholders})
        """,
        [user_id, *unique_ids],
    ).fetchall()
    owned = {int(row["id"]) for row in rows}
    if owned != set(unique_ids):
        raise_api_error(
            status.HTTP_400_BAD_REQUEST,
            "todos_not_owned",
            "存在不属于当前用户的待办",
        )

    # 去重后发送给 AI（保留请求顺序）
    seen_ids: set[int] = set()
    items: list[dict[str, object]] = []
    for item in payload.items:
        if item.id in seen_ids:
            continue
        seen_ids.add(item.id)
        items.append({"id": item.id, "content": item.content, "due_time": item.due_time})

    try:
        groups = await organize_todos_with_deepseek(payload.view, items)
    except DeepSeekParseError as exc:
        raise_api_error(
            status.HTTP_502_BAD_GATEWAY,
            "organize_failed",
            "AI 整理失败，请稍后重试",
        )

    return OrganizeResponse(view=payload.view, groups=groups)


@router.patch("/{todo_id}", response_model=TodoPublic)
def patch_todo(
    todo_id: int,
    payload: TodoUpdateRequest,
    db: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user_invited),
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
    if "pinned" in fields:
        values["pinned"] = payload.pinned
    if "deleted_at" in fields:
        # 恢复：deleted_at=None 清除删除标记（日期归正由客户端决定，见 v2-04）
        values["deleted_at"] = payload.deleted_at

    updated = update_todo(db, int(user["id"]), todo_id, values)
    if updated is None:
        raise_api_error(status.HTTP_404_NOT_FOUND, "todo_not_found", "待办不存在")
    return updated


@router.delete("/{todo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_todo(
    todo_id: int,
    db: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user_invited),
) -> None:
    deleted = soft_delete_todo(db, int(user["id"]), todo_id)
    if not deleted:
        raise_api_error(status.HTTP_404_NOT_FOUND, "todo_not_found", "待办不存在")
    return None
