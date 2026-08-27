from __future__ import annotations

import logging
import sqlite3
from time import perf_counter

from fastapi import APIRouter, Depends, status

from app.deps import current_user_invited, get_db
from app.errors import raise_api_error
from app.schemas import (
    BatchCreateRequest,
    BatchCreateResponse,
    OrganizeRequest,
    OrganizeResponse,
    ParsedItemOut,
    TodoListResponse,
    TodoParseRequest,
    TodoParseResponse,
    TodoPublic,
    TodoUpdateRequest,
)
from app.services.deepseek import (
    DeepSeekParseError,
    NoTodoParsedError,
    TokenUsage,
    organize_todos_with_deepseek,
    parse_todos_with_deepseek,
)
from app.services.quota import check_ai_quota, record_ai_usage
from app.services.todos import create_todos, list_grouped_todos, soft_delete_todo, update_todo

router = APIRouter(prefix="/api/todos", tags=["todos"])
logger = logging.getLogger("uvicorn.error")


def _elapsed_ms(started_at: float) -> int:
    return round((perf_counter() - started_at) * 1000)


def _record_ai_usage(
    db: sqlite3.Connection,
    user_id: int,
    purpose: str,
    status: str,
    usage: TokenUsage | None,
    *,
    error_code: str | None,
    started_at: float,
) -> None:
    """Persist an AI usage row. ``usage`` may be None when the upstream call
    never produced a token block (network failure) — then a failed row with
    zero tokens is still recorded so the call itself is accounted for."""
    if usage is None:
        usage = TokenUsage()
    record_ai_usage(
        db,
        user_id,
        purpose=purpose,
        status=status,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
        cache_hit_tokens=usage.cache_hit_tokens,
        cache_miss_tokens=usage.cache_miss_tokens,
        error_code=error_code,
        duration_ms=_elapsed_ms(started_at),
    )


@router.get("", response_model=TodoListResponse)
def list_todos(
    db: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user_invited),
):
    return list_grouped_todos(db, int(user["id"]))


@router.post("/parse", response_model=TodoParseResponse)
async def parse_todos(
    payload: TodoParseRequest,
    db: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user_invited),
):
    user_id = int(user["id"])
    started_at = perf_counter()
    try:
        check_ai_quota(db, user_id)
        outcome = await parse_todos_with_deepseek(payload.transcript)
    except NoTodoParsedError as exc:
        # Tokens were consumed even though no todo was parsed: still count them.
        _record_ai_usage(db, user_id, "parse", "success", exc.usage, error_code=None, started_at=started_at)
        logger.info(
            "todos_parse_done elapsed_ms=%s transcript_chars=%s source=%s items=0",
            _elapsed_ms(started_at),
            len(payload.transcript),
            payload.source,
        )
        return TodoParseResponse(
            transcript=payload.transcript,
            items=[],
            message=str(exc),
        )
    except DeepSeekParseError as exc:
        _record_ai_usage(db, user_id, "parse", "failed", exc.usage, error_code="parse_error", started_at=started_at)
        logger.warning(
            "todos_parse_failed elapsed_ms=%s transcript_chars=%s source=%s error=%s detail=%s",
            _elapsed_ms(started_at),
            len(payload.transcript),
            payload.source,
            exc,
            exc.detail,
        )
        raise_api_error(
            status.HTTP_502_BAD_GATEWAY,
            "todo_parse_unavailable",
            "解析服务暂时不可用，请稍后重试",
        )

    _record_ai_usage(db, user_id, "parse", "success", outcome.usage, error_code=None, started_at=started_at)
    logger.info(
        "todos_parse_done elapsed_ms=%s transcript_chars=%s source=%s items=%s",
        _elapsed_ms(started_at),
        len(payload.transcript),
        payload.source,
        len(outcome.items),
    )
    return TodoParseResponse(
        transcript=payload.transcript,
        items=[ParsedItemOut.model_validate(item) for item in outcome.items],
    )


@router.post(
    "/batch",
    response_model=BatchCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def batch_create_todos(
    payload: BatchCreateRequest,
    db: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user_invited),
):
    started_at = perf_counter()
    items = [
        {
            "content": item.content,
            "due_date": item.due_date.isoformat(),
            "due_time": item.due_time,
        }
        for item in payload.items
    ]
    try:
        created = create_todos(db, int(user["id"]), items)
    except sqlite3.Error:
        logger.exception(
            "todos_batch_failed elapsed_ms=%s items=%s",
            _elapsed_ms(started_at),
            len(items),
        )
        raise_api_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "todo_save_failed",
            "保存待办失败，请稍后重试",
        )

    logger.info(
        "todos_batch_done elapsed_ms=%s items=%s",
        _elapsed_ms(started_at),
        len(created),
    )
    return BatchCreateResponse(items=created)


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

    started_at = perf_counter()
    try:
        check_ai_quota(db, user_id)
        outcome = await organize_todos_with_deepseek(payload.view, items)
    except DeepSeekParseError as exc:
        _record_ai_usage(db, user_id, "organize", "failed", exc.usage, error_code="organize_error", started_at=started_at)
        raise_api_error(
            status.HTTP_502_BAD_GATEWAY,
            "organize_failed",
            "AI 整理失败，请稍后重试",
        )

    _record_ai_usage(db, user_id, "organize", "success", outcome.usage, error_code=None, started_at=started_at)
    return OrganizeResponse(view=payload.view, groups=outcome.groups)


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
