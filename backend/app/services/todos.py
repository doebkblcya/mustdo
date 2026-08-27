from __future__ import annotations

import sqlite3
from datetime import date

from app.schemas import ReminderPublic, TodoGroups, TodoListResponse, TodoPublic
from app.services.reminders import cancel_reminder, get_reminder
from app.time_utils import today_date, tomorrow_date, utcish_now_iso


def row_to_todo(row: sqlite3.Row) -> TodoPublic:
    todo = TodoPublic(
        id=row["id"],
        content=row["content"],
        due_date=date.fromisoformat(row["due_date"]),
        due_time=row["due_time"],
        status=row["status"],
        pinned=bool(row["pinned"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
    # list_grouped_todos 用 LEFT JOIN 带出提醒摘要（r_* 前缀列）
    if "r_remind_at" in row.keys() and row["r_remind_at"] is not None and row["r_status"] != "cancelled":
        todo.reminder = ReminderPublic(
            remind_at=row["r_remind_at"],
            status=row["r_status"],
            error_code=row["r_error_code"],
        )
    return todo


def _todo_sort_key(todo: TodoPublic) -> tuple[bool, bool, bool, str, int]:
    return (
        not todo.pinned,
        todo.status == "done",
        todo.due_time is not None,
        todo.due_time or "",
        todo.id,
    )


def list_grouped_todos(db: sqlite3.Connection, user_id: int) -> TodoListResponse:
    today = today_date()
    tomorrow = tomorrow_date()
    rows = db.execute(
        """
        SELECT t.*, r.remind_at AS r_remind_at, r.status AS r_status, r.error_code AS r_error_code
        FROM todos t
        LEFT JOIN todo_reminders r ON r.todo_id = t.id
        WHERE t.user_id = ?
          AND t.deleted_at IS NULL
          AND t.due_date >= ?
        ORDER BY t.due_date ASC, t.id ASC
        """,
        (user_id, today.isoformat()),
    ).fetchall()

    groups = {"today": [], "tomorrow": [], "upcoming": []}
    for row in rows:
        todo = row_to_todo(row)
        if todo.due_date == today:
            groups["today"].append(todo)
        elif todo.due_date == tomorrow:
            groups["tomorrow"].append(todo)
        elif todo.due_date > tomorrow:
            groups["upcoming"].append(todo)

    return TodoListResponse(
        today_date=today,
        tomorrow_date=tomorrow,
        groups=TodoGroups(
            today=sorted(groups["today"], key=_todo_sort_key),
            tomorrow=sorted(groups["tomorrow"], key=_todo_sort_key),
            upcoming=sorted(groups["upcoming"], key=lambda item: (item.due_date, *_todo_sort_key(item))),
        ),
    )


def get_owned_todo(db: sqlite3.Connection, user_id: int, todo_id: int) -> sqlite3.Row | None:
    return db.execute(
        """
        SELECT *
        FROM todos
        WHERE id = ? AND user_id = ? AND deleted_at IS NULL
        """,
        (todo_id, user_id),
    ).fetchone()


def _get_owned_todo_any(db: sqlite3.Connection, user_id: int, todo_id: int) -> sqlite3.Row | None:
    """Fetch an owned todo regardless of deleted state (restore targets soft-deleted rows)."""
    return db.execute(
        "SELECT * FROM todos WHERE id = ? AND user_id = ?",
        (todo_id, user_id),
    ).fetchone()


def update_todo(
    db: sqlite3.Connection,
    user_id: int,
    todo_id: int,
    values: dict[str, object],
) -> TodoPublic | None:
    row = _get_owned_todo_any(db, user_id, todo_id)
    if row is None:
        return None
    if not values:
        return row_to_todo(row)

    allowed = {"content", "due_date", "due_time", "status", "pinned", "deleted_at"}
    assignments = []
    params = []
    for key, value in values.items():
        if key not in allowed:
            continue
        assignments.append(f"{key} = ?")
        if isinstance(value, bool):
            params.append(1 if value else 0)
        elif isinstance(value, date):
            params.append(value.isoformat())
        else:
            params.append(value)

    if not assignments:
        return row_to_todo(row)

    assignments.append("updated_at = ?")
    params.append(utcish_now_iso())
    params.extend([todo_id, user_id])
    db.execute(
        f"""
        UPDATE todos
        SET {", ".join(assignments)}
        WHERE id = ? AND user_id = ?
        """,
        params,
    )
    # 状态联动：完成 / 改期（日期或具体时间）→ 取消提醒
    if {"due_date", "due_time", "status"} & values.keys():
        cancel_reminder(db, user_id, todo_id)
    db.commit()
    updated = row_to_todo(_get_owned_todo_any(db, user_id, todo_id))
    updated.reminder = get_reminder(db, todo_id)
    return updated


def soft_delete_todo(db: sqlite3.Connection, user_id: int, todo_id: int) -> bool:
    now = utcish_now_iso()
    cursor = db.execute(
        """
        UPDATE todos
        SET deleted_at = ?, updated_at = ?
        WHERE id = ? AND user_id = ? AND deleted_at IS NULL
        """,
        (now, now, todo_id, user_id),
    )
    if cursor.rowcount > 0:
        cancel_reminder(db, user_id, todo_id)
    db.commit()
    return cursor.rowcount > 0


def create_todos(
    db: sqlite3.Connection,
    user_id: int,
    items: list[dict[str, str | None]],
) -> list[TodoPublic]:
    if not items:
        return []

    now = utcish_now_iso()
    created_ids: list[int] = []
    try:
        db.execute("BEGIN IMMEDIATE")
        for item in items:
            cursor = db.execute(
                """
                INSERT INTO todos (
                    user_id, content, due_date, due_time, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    user_id,
                    item["content"],
                    item["due_date"],
                    item.get("due_time"),
                    now,
                    now,
                ),
            )
            created_ids.append(int(cursor.lastrowid))
        db.commit()
    except sqlite3.Error:
        db.rollback()
        raise

    placeholders = ",".join("?" for _ in created_ids)
    rows = db.execute(
        f"SELECT * FROM todos WHERE id IN ({placeholders}) ORDER BY id ASC",
        created_ids,
    ).fetchall()
    return [row_to_todo(row) for row in rows]
