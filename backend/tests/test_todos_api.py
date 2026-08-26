from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import AsyncMock, patch


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from fastapi import HTTPException  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import get_connection, init_db  # noqa: E402
from app.routers.todos import (  # noqa: E402
    batch_create_todos,
    delete_todo,
    organize_todos,
    parse_todos,
)
from app.schemas import (  # noqa: E402
    BatchCreateRequest,
    OrganizeRequest,
    TodoParseRequest,
)
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
                INSERT INTO users (wechat_openid, status, created_at, updated_at)
                VALUES ('openid-test', 'active', ?, ?)
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

    def test_organize_rejects_foreign_todo(self) -> None:
        user_id, _todo_id = self._create_todo()
        db = get_connection()
        try:
            payload = OrganizeRequest(
                view="today",
                items=[{"id": 999999, "content": "外部待办", "due_time": None}],
            )
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(organize_todos(payload, db=db, user={"id": user_id}))
        finally:
            db.close()

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(raised.exception.detail["code"], "todos_not_owned")

    def test_organize_returns_validated_groups(self) -> None:
        user_id, todo_id = self._create_todo()
        db = get_connection()
        payload = OrganizeRequest(
            view="today",
            items=[{"id": todo_id, "content": "测试删除", "due_time": None}],
        )
        fake_groups = [{"name": "工作", "todo_ids": [todo_id]}]
        with patch(
            "app.routers.todos.organize_todos_with_deepseek",
            new=AsyncMock(return_value=fake_groups),
        ):
            try:
                result = asyncio.run(organize_todos(payload, db=db, user={"id": user_id}))
            finally:
                db.close()

        self.assertEqual(result.view, "today")
        self.assertEqual(len(result.groups), 1)
        self.assertEqual(result.groups[0].name, "工作")
        self.assertEqual(result.groups[0].todo_ids, [todo_id])

    def test_parse_returns_items_without_writing_todos(self) -> None:
        user_id, _todo_id = self._create_todo()
        db = get_connection()
        before = db.execute("SELECT COUNT(*) AS count FROM todos").fetchone()["count"]
        fake_items = [
            {
                "content": "买菜",
                "due_date": today_date().isoformat(),
                "due_time": "15:00",
            }
        ]
        with patch(
            "app.routers.todos.parse_todos_with_deepseek",
            new=AsyncMock(return_value=fake_items),
        ):
            result = asyncio.run(
                parse_todos(
                    TodoParseRequest(transcript="今天下午三点买菜", source="text"),
                    user={"id": user_id},
                )
            )
        after = db.execute("SELECT COUNT(*) AS count FROM todos").fetchone()["count"]
        db.close()

        self.assertEqual(before, after)
        self.assertEqual(result.transcript, "今天下午三点买菜")
        self.assertEqual(result.items[0].content, "买菜")
        self.assertEqual(result.items[0].due_time, "15:00")

    def test_batch_creates_all_items_and_returns_public_todos(self) -> None:
        user_id, _todo_id = self._create_todo()
        db = get_connection()
        try:
            result = batch_create_todos(
                BatchCreateRequest(
                    items=[
                        {
                            "content": "  买   菜  ",
                            "due_date": today_date() - timedelta(days=3),
                            "due_time": "",
                        },
                        {
                            "content": "交房租",
                            "due_date": today_date() + timedelta(days=2),
                            "due_time": "09:30",
                        },
                    ]
                ),
                db=db,
                user={"id": user_id},
            )
        finally:
            db.close()

        self.assertEqual(len(result.items), 2)
        self.assertEqual(result.items[0].content, "买 菜")
        self.assertEqual(result.items[0].due_date, today_date())
        self.assertIsNone(result.items[0].due_time)
        self.assertEqual(result.items[1].due_time, "09:30")


if __name__ == "__main__":
    unittest.main()
