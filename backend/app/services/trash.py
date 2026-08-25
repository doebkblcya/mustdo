from __future__ import annotations

import sqlite3
from datetime import date

from app.schemas import TrashItem, TrashListResponse
from app.time_utils import today_date


def row_to_trash_item(row: sqlite3.Row) -> TrashItem:
    return TrashItem(
        id=row["id"],
        content=row["content"],
        due_date=date.fromisoformat(row["due_date"]),
        due_time=row["due_time"],
        status=row["status"],
        pinned=bool(row["pinned"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        deleted_at=row["deleted_at"],
    )


def _counts(db: sqlite3.Connection, user_id: int) -> tuple[int, int]:
    today = today_date().isoformat()
    deleted = db.execute(
        "SELECT COUNT(*) FROM todos WHERE user_id = ? AND deleted_at IS NOT NULL",
        (user_id,),
    ).fetchone()[0]
    overdue = db.execute(
        """
        SELECT COUNT(*) FROM todos
        WHERE user_id = ? AND deleted_at IS NULL
          AND status = 'pending' AND due_date < ?
        """,
        (user_id, today),
    ).fetchone()[0]
    return int(deleted), int(overdue)


def list_trash(db: sqlite3.Connection, user_id: int, type: str | None) -> TrashListResponse:
    deleted_count, overdue_count = _counts(db, user_id)

    items: list[TrashItem] = []
    if type == "deleted":
        rows = db.execute(
            """
            SELECT * FROM todos
            WHERE user_id = ? AND deleted_at IS NOT NULL
            ORDER BY deleted_at DESC, id DESC
            """,
            (user_id,),
        ).fetchall()
        items = [row_to_trash_item(row) for row in rows]
    elif type == "overdue":
        today = today_date().isoformat()
        rows = db.execute(
            """
            SELECT * FROM todos
            WHERE user_id = ? AND deleted_at IS NULL
              AND status = 'pending' AND due_date < ?
            ORDER BY due_date DESC, id DESC
            """,
            (user_id, today),
        ).fetchall()
        items = [row_to_trash_item(row) for row in rows]

    return TrashListResponse(
        deleted_count=deleted_count,
        overdue_count=overdue_count,
        items=items,
    )
