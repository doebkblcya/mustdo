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
# 订阅消息模板字段名 —— 必须与公众平台「待办事项提醒」模板里
# 勾选的关键词逐字一致。若勾选的关键词有出入，只改这里。
# ============================================================
FIELD_CONTENT = "事项主题"
FIELD_TIME = "事项时间"
FIELD_NOTE = "备注消息"

DEFAULT_INTERVAL_SECONDS = 30


def build_message_data(row: sqlite3.Row) -> dict[str, dict[str, str]]:
    due = f"{row['due_date']} {row['due_time']}" if row["due_time"] else row["due_date"]
    return {
        FIELD_CONTENT: {"value": row["content"]},
        FIELD_TIME: {"value": due},
        FIELD_NOTE: {"value": "点击查看详情"},
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
