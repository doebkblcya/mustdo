from __future__ import annotations

import asyncio
import logging
import sqlite3

from app.config import get_settings
from app.db import get_connection
from app.services.reminders import (
    fetch_due_pending,
    mark_reminder_failed,
    mark_reminder_sent,
)
from app.services.subscribe import SubscribeSendError, send_subscribe_message
from app.time_utils import utcish_now_iso

logger = logging.getLogger("uvicorn.error")

# ============================================================
# 订阅消息模板字段 ID —— 必须与公众平台「待办事项提醒」模板详情里的
# 字段标识逐字一致（见模板详情页 {{thing1.DATA}} / {{time2.DATA}}）。
# thing1=事项主题（thing 类型，≤20 字）；time2=事项时间（time 类型）。
# 若调整模板，只改这里；字段 ID 与模板不符会报 47003。
# ============================================================
FIELD_CONTENT = "thing1"
FIELD_TIME = "time2"

DEFAULT_INTERVAL_SECONDS = 30

# thing 类型字段微信限制 20 字符，超长截断避免 47003
CONTENT_MAX_CHARS = 20


def build_message_data(row: sqlite3.Row) -> dict[str, dict[str, str]]:
    # 事项时间：time 类型字段仅接受 HH:MM（如 14:30），不接受"时+日期"组合
    return {
        FIELD_CONTENT: {"value": (row["content"] or "")[:CONTENT_MAX_CHARS]},
        FIELD_TIME: {"value": row["due_time"]},
    }


async def send_due_reminders_once() -> int:
    """Dispatch every due pending reminder; returns the number handled.

    Sending is per-row: success → sent, failure → failed (with errcode kept).
    Missing template config keeps reminders pending so they fire once configured.
    """
    settings = get_settings()
    if not settings.wechat_template_id:
        logger.warning("wechat_template_id_missing skip reminder dispatch")
        return 0

    db = get_connection()
    try:
        rows = fetch_due_pending(db, utcish_now_iso())
        if not rows:
            return 0
        for row in rows:
            data = build_message_data(row)
            try:
                await send_subscribe_message(
                    openid=row["wechat_openid"],
                    template_id=settings.wechat_template_id,
                    page=f"pages/todos/todos?id={row['todo_id']}",
                    data=data,
                )
                mark_reminder_sent(db, row["reminder_id"], utcish_now_iso())
                logger.info("reminder_sent todo_id=%s remind_at=%s", row["todo_id"], row["remind_at"])
            except SubscribeSendError as exc:
                mark_reminder_failed(db, row["reminder_id"], exc.code)
                logger.warning(
                    "reminder_send_failed todo_id=%s errcode=%s message=%s",
                    row["todo_id"],
                    exc.code,
                    exc.message,
                )
        return len(rows)
    finally:
        db.close()


async def reminder_loop(interval_seconds: int = DEFAULT_INTERVAL_SECONDS) -> None:
    """Lifespan background loop. Single worker (WORKERS=1) guarantees a single
    dispatcher; on restart the loop immediately re-scans pending reminders."""
    while True:
        try:
            await send_due_reminders_once()
        except Exception:
            logger.exception("reminder_loop_error")
        await asyncio.sleep(interval_seconds)
