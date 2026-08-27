from __future__ import annotations

import sqlite3
from datetime import datetime

from fastapi import status

from app.config import get_settings
from app.errors import raise_api_error
from app.schemas import ReminderPublic
from app.time_utils import utcish_now_iso

# 仅这些状态的提醒视为「有效」（对用户展示为已开启 / 待发送）。
# 收紧为仅 pending：sent 已发完、failed 已失败、cancelled 已取消，都不再算开启中。
ACTIVE_STATUSES = ("pending",)


def normalize_remind_at(value: datetime) -> str:
    """Normalize a client datetime to the local (Asia/Shanghai) ISO string convention.

    Naive datetimes are treated as local time; aware datetimes are converted.
    Produces e.g. ``2026-08-25T14:30:00+08:00`` — lexicographic comparison with
    ``utcish_now_iso()`` output is safe because both are local-ISO strings.
    """
    tz = get_settings().tzinfo
    if value.tzinfo is None:
        value = value.replace(tzinfo=tz)
    else:
        value = value.astimezone(tz)
    return value.isoformat(timespec="seconds")


def _row_to_reminder(row: sqlite3.Row) -> ReminderPublic:
    return ReminderPublic(
        remind_at=row["remind_at"],
        status=row["status"],
        error_code=row["error_code"],
    )


def upsert_reminder(
    db: sqlite3.Connection,
    user_id: int,
    todo_id: int,
    remind_at: str,
) -> ReminderPublic:
    """Create or replace the todo's reminder.

    Validates ownership, non-deleted state, pending status, an explicit
    ``due_time`` and a future ``remind_at``. Overwrites any existing row
    (todo_id is UNIQUE), which enforces 「每条待办同时保留一个有效提醒」.
    """
    row = db.execute(
        "SELECT * FROM todos WHERE id = ? AND user_id = ? AND deleted_at IS NULL",
        (todo_id, user_id),
    ).fetchone()
    if row is None:
        raise_api_error(status.HTTP_404_NOT_FOUND, "todo_not_found", "待办不存在")
    if row["status"] == "done":
        raise_api_error(status.HTTP_400_BAD_REQUEST, "reminder_todo_done", "已完成待办无法设置提醒")
    if row["due_time"] is None:
        raise_api_error(status.HTTP_400_BAD_REQUEST, "reminder_requires_time", "请先设置明确时间")
    if remind_at <= utcish_now_iso():
        raise_api_error(status.HTTP_400_BAD_REQUEST, "reminder_time_in_past", "提醒时间必须晚于当前时间")

    now = utcish_now_iso()
    db.execute(
        """
        INSERT INTO todo_reminders (todo_id, user_id, remind_at, status, created_at, updated_at)
        VALUES (?, ?, ?, 'pending', ?, ?)
        ON CONFLICT(todo_id) DO UPDATE SET
            user_id = excluded.user_id,
            remind_at = excluded.remind_at,
            status = 'pending',
            sent_at = NULL,
            error_code = NULL,
            updated_at = excluded.updated_at
        """,
        (todo_id, user_id, remind_at, now, now),
    )
    db.commit()
    fetched = db.execute(
        "SELECT remind_at, status, error_code FROM todo_reminders WHERE todo_id = ?",
        (todo_id,),
    ).fetchone()
    return _row_to_reminder(fetched)


def cancel_reminder(db: sqlite3.Connection, user_id: int, todo_id: int) -> None:
    """Cancel the todo's effective reminder (pending/failed → cancelled).

    Used by the DELETE endpoint and by state linkage (done / deleted /
    due_date / due_time changes). Raises 404 when the todo is not owned.
    """
    owned = db.execute(
        "SELECT id FROM todos WHERE id = ? AND user_id = ?",
        (todo_id, user_id),
    ).fetchone()
    if owned is None:
        raise_api_error(status.HTTP_404_NOT_FOUND, "todo_not_found", "待办不存在")
    db.execute(
        """
        UPDATE todo_reminders
        SET status = 'cancelled', updated_at = ?
        WHERE todo_id = ? AND user_id = ? AND status IN ('pending', 'failed')
        """,
        (utcish_now_iso(), todo_id, user_id),
    )
    db.commit()


def get_reminder(db: sqlite3.Connection, todo_id: int) -> ReminderPublic | None:
    """Effective reminder summary for a todo; only pending rows read as active."""
    row = db.execute(
        """
        SELECT remind_at, status, error_code
        FROM todo_reminders
        WHERE todo_id = ?
        """,
        (todo_id,),
    ).fetchone()
    if row is None or row["status"] != "pending":
        return None
    return _row_to_reminder(row)


def fetch_due_pending(db: sqlite3.Connection, now: str) -> list[sqlite3.Row]:
    """Due, unsent reminders joined with todo content and the user's openid."""
    return db.execute(
        """
        SELECT r.id AS reminder_id, r.todo_id, r.remind_at,
               t.content, t.due_date, t.due_time,
               u.wechat_openid
        FROM todo_reminders r
        JOIN todos t ON t.id = r.todo_id
        JOIN users u ON u.id = r.user_id
        WHERE r.status = 'pending'
          AND r.remind_at <= ?
          AND t.deleted_at IS NULL
        ORDER BY r.remind_at ASC
        """,
        (now,),
    ).fetchall()


def mark_reminder_sent(db: sqlite3.Connection, reminder_id: int, sent_at: str) -> None:
    db.execute(
        "UPDATE todo_reminders SET status = 'sent', sent_at = ?, updated_at = ? WHERE id = ?",
        (sent_at, sent_at, reminder_id),
    )
    db.commit()


def mark_reminder_failed(db: sqlite3.Connection, reminder_id: int, error_code: str) -> None:
    db.execute(
        "UPDATE todo_reminders SET status = 'failed', error_code = ?, updated_at = ? WHERE id = ?",
        (error_code, utcish_now_iso(), reminder_id),
    )
    db.commit()
