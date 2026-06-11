from __future__ import annotations

import sqlite3
from datetime import date

from app.schemas import TodoGroups, TodoListResponse, TodoPublic
from app.time_utils import today_date, tomorrow_date, utcish_now_iso


def row_to_todo(row: sqlite3.Row) -> TodoPublic:
    return TodoPublic(
        id=row["id"],
        content=row["content"],
        due_date=date.fromisoformat(row["due_date"]),
        due_time=row["due_time"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _todo_sort_key(todo: TodoPublic) -> tuple[bool, bool, str, int]:
    return (
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
        SELECT *
        FROM todos
        WHERE user_id = ?
          AND deleted_at IS NULL
          AND due_date >= ?
        ORDER BY due_date ASC, id ASC
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


def update_todo(
    db: sqlite3.Connection,
    user_id: int,
    todo_id: int,
    values: dict[str, object],
) -> TodoPublic | None:
    if get_owned_todo(db, user_id, todo_id) is None:
        return None
    if not values:
        return row_to_todo(get_owned_todo(db, user_id, todo_id))

    allowed = {"content", "due_date", "due_time", "status"}
    assignments = []
    params = []
    for key, value in values.items():
        if key not in allowed:
            continue
        assignments.append(f"{key} = ?")
        if isinstance(value, date):
            params.append(value.isoformat())
        else:
            params.append(value)

    if not assignments:
        return row_to_todo(get_owned_todo(db, user_id, todo_id))

    assignments.append("updated_at = ?")
    params.append(utcish_now_iso())
    params.extend([todo_id, user_id])
    db.execute(
        f"""
        UPDATE todos
        SET {", ".join(assignments)}
        WHERE id = ? AND user_id = ? AND deleted_at IS NULL
        """,
        params,
    )
    db.commit()
    return row_to_todo(get_owned_todo(db, user_id, todo_id))


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
        with db:
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
    except sqlite3.Error:
        raise

    placeholders = ",".join("?" for _ in created_ids)
    rows = db.execute(
        f"SELECT * FROM todos WHERE id IN ({placeholders}) ORDER BY id ASC",
        created_ids,
    ).fetchall()
    return [row_to_todo(row) for row in rows]


def cleanup_overdue_todos(db: sqlite3.Connection) -> int:
    cursor = db.execute(
        "DELETE FROM todos WHERE due_date < ?",
        (today_date().isoformat(),),
    )
    db.commit()
    return cursor.rowcount
