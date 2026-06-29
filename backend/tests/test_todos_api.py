from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from fastapi import HTTPException  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import get_connection, init_db  # noqa: E402
from app.routers.todos import delete_todo  # noqa: E402
from app.time_utils import now_shanghai, today_date  # noqa: E402


class TodoApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.env = patch.dict(
            os.environ,
            {
                "DATABASE_PATH": os.path.join(self.tmpdir.name, "test.db"),
                "SECRET_KEY": "test-secret",
            },
            clear=False,
        )
        self.env.start()
        get_settings.cache_clear()
        init_db()

    def tearDown(self) -> None:
        self.env.stop()
        self.tmpdir.cleanup()
        get_settings.cache_clear()

    def _create_todo(self) -> tuple[int, int]:
        now = now_shanghai()
        db = get_connection()
        try:
            user = db.execute(
                """
                INSERT INTO users (
                    username, username_normalized, password_hash, status, created_at, updated_at
                )
                VALUES ('tester', 'tester', 'hash', 'active', ?, ?)
                """,
                (now.isoformat(timespec="seconds"), now.isoformat(timespec="seconds")),
            )
            user_id = int(user.lastrowid)
            todo = db.execute(
                """
                INSERT INTO todos (
                    user_id, content, due_date, due_time, status, created_at, updated_at
                )
                VALUES (?, '测试删除', ?, NULL, 'pending', ?, ?)
                """,
                (
                    user_id,
                    today_date().isoformat(),
                    now.isoformat(timespec="seconds"),
                    now.isoformat(timespec="seconds"),
                ),
            )
            db.commit()
            return user_id, int(todo.lastrowid)
        finally:
            db.close()

    def test_delete_todo_returns_none_for_204_response(self) -> None:
        user_id, todo_id = self._create_todo()
        db = get_connection()
        try:
            result = delete_todo(todo_id, db=db, user={"id": user_id})
            row = db.execute("SELECT deleted_at FROM todos WHERE id = ?", (todo_id,)).fetchone()
        finally:
            db.close()

        self.assertIsNone(result)
        self.assertIsNotNone(row["deleted_at"])

    def test_delete_missing_todo_raises_404(self) -> None:
        user_id, _todo_id = self._create_todo()
        db = get_connection()
        try:
            with self.assertRaises(HTTPException) as raised:
                delete_todo(999999, db=db, user={"id": user_id})
        finally:
            db.close()

        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(raised.exception.detail["code"], "todo_not_found")
        self.assertEqual(raised.exception.detail["message"], "待办不存在")


if __name__ == "__main__":
    unittest.main()
