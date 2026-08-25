from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from app.config import get_settings  # noqa: E402
from app.db import get_connection, init_db  # noqa: E402
from app.routers.todos import delete_todo, patch_todo  # noqa: E402
from app.routers.trash import get_trash  # noqa: E402
from app.schemas import TodoUpdateRequest  # noqa: E402
from app.time_utils import now_shanghai, today_date  # noqa: E402


class TrashApiTests(unittest.TestCase):
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

    def _create_user(self, openid: str = "openid-a") -> int:
        now = now_shanghai()
        db = get_connection()
        try:
            cur = db.execute(
                """
                INSERT INTO users (wechat_openid, status, created_at, updated_at)
                VALUES (?, 'active', ?, ?)
                """,
                (openid, now.isoformat(timespec="seconds"), now.isoformat(timespec="seconds")),
            )
            db.commit()
            return int(cur.lastrowid)
        finally:
            db.close()

    def _create_todo(
        self,
        user_id: int,
        due_date: str | None = None,
        due_time: str | None = None,
        status: str = "pending",
        content: str = "事项",
    ) -> int:
        now = now_shanghai()
        db = get_connection()
        try:
            cur = db.execute(
                """
                INSERT INTO todos (
                    user_id, content, due_date, due_time, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    content,
                    due_date or today_date().isoformat(),
                    due_time,
                    status,
                    now.isoformat(timespec="seconds"),
                    now.isoformat(timespec="seconds"),
                ),
            )
            db.commit()
            return int(cur.lastrowid)
        finally:
            db.close()

    def _soft_delete(self, todo_id: int, when: str | None = None) -> None:
        db = get_connection()
        try:
            ts = when or now_shanghai().isoformat(timespec="seconds")
            db.execute("UPDATE todos SET deleted_at = ? WHERE id = ?", (ts, todo_id))
            db.commit()
        finally:
            db.close()

    def _patch(self, todo_id: int, user_id: int, payload: dict):
        db = get_connection()
        try:
            return patch_todo(todo_id, TodoUpdateRequest(**payload), db=db, user={"id": user_id})
        finally:
            db.close()

    def test_summary_without_type(self) -> None:
        uid = self._create_user()
        t1 = self._create_todo(uid)
        t2 = self._create_todo(uid, due_date=(today_date() - timedelta(days=2)).isoformat())
        self._soft_delete(t1)
        db = get_connection()
        try:
            res = get_trash(None, db=db, user={"id": uid})
        finally:
            db.close()

        self.assertEqual(res.deleted_count, 1)
        self.assertEqual(res.overdue_count, 1)
        self.assertEqual(res.items, [])

    def test_deleted_list_sorted_desc_with_fields(self) -> None:
        uid = self._create_user()
        t_old = self._create_todo(uid, due_time="09:30", status="done", content="旧事项")
        t_new = self._create_todo(uid, due_time="21:00", content="新事项")
        self._soft_delete(t_old, "2026-01-01T10:00:00+08:00")
        self._soft_delete(t_new, "2026-01-02T10:00:00+08:00")

        db = get_connection()
        try:
            res = get_trash("deleted", db=db, user={"id": uid})
        finally:
            db.close()

        self.assertEqual(res.deleted_count, 2)
        self.assertEqual([item.id for item in res.items], [t_new, t_old])
        item = res.items[1]
        self.assertEqual(item.content, "旧事项")
        self.assertEqual(item.due_time, "09:30")
        self.assertEqual(item.status, "done")
        self.assertEqual(item.deleted_at, "2026-01-01T10:00:00+08:00")

    def test_overdue_list_filters_and_sorts(self) -> None:
        uid = self._create_user()
        today = today_date()
        t_old = self._create_todo(uid, due_date=(today - timedelta(days=4)).isoformat())
        t_new = self._create_todo(uid, due_date=(today - timedelta(days=1)).isoformat())
        self._create_todo(uid)  # 今天 → 不逾期
        self._create_todo(uid, due_date=(today - timedelta(days=3)).isoformat(), status="done")  # 已完成 → 不显示

        db = get_connection()
        try:
            res = get_trash("overdue", db=db, user={"id": uid})
        finally:
            db.close()

        self.assertEqual(res.overdue_count, 2)
        self.assertEqual([item.id for item in res.items], [t_new, t_old])

    def test_user_isolation(self) -> None:
        uid_a = self._create_user("openid-a")
        uid_b = self._create_user("openid-b")
        t1 = self._create_todo(uid_a)
        self._create_todo(uid_a, due_date=(today_date() - timedelta(days=2)).isoformat())
        self._soft_delete(t1)

        db = get_connection()
        try:
            res = get_trash("deleted", db=db, user={"id": uid_b})
        finally:
            db.close()

        self.assertEqual(res.deleted_count, 0)
        self.assertEqual(res.overdue_count, 0)
        self.assertEqual(res.items, [])

    def test_restore_via_patch_clears_deleted_at(self) -> None:
        uid = self._create_user()
        t = self._create_todo(uid, due_time="09:30", status="done", content="原事项")
        self._soft_delete(t)

        result = self._patch(t, uid, {"deleted_at": None})

        db = get_connection()
        try:
            row = db.execute("SELECT * FROM todos WHERE id = ?", (t,)).fetchone()
        finally:
            db.close()

        self.assertIsNone(row["deleted_at"])
        # 内容 / 时间 / 状态 / 置顶保留
        self.assertEqual(row["content"], "原事项")
        self.assertEqual(row["due_time"], "09:30")
        self.assertEqual(row["status"], "done")
        self.assertIsNotNone(result)

    def test_restore_with_date_normalization(self) -> None:
        uid = self._create_user()
        past = (today_date() - timedelta(days=3)).isoformat()
        t = self._create_todo(uid, due_date=past)
        self._soft_delete(t)

        # 客户端恢复：原日期早于今天 → 归正为今天
        today = today_date().isoformat()
        result = self._patch(t, uid, {"deleted_at": None, "due_date": today})

        self.assertEqual(str(result.due_date), today)

    def test_patch_soft_deleted_todo_allowed(self) -> None:
        uid = self._create_user()
        t = self._create_todo(uid)
        self._soft_delete(t)

        self._patch(t, uid, {"content": "修改后"})

        db = get_connection()
        try:
            row = db.execute("SELECT * FROM todos WHERE id = ?", (t,)).fetchone()
        finally:
            db.close()
        self.assertEqual(row["content"], "修改后")
        self.assertIsNotNone(row["deleted_at"])  # 仍处于删除状态

    def test_patch_foreign_or_missing_todo_404(self) -> None:
        uid_a = self._create_user("openid-a")
        uid_b = self._create_user("openid-b")
        t = self._create_todo(uid_a)
        self._soft_delete(t)

        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as raised:
            self._patch(t, uid_b, {"deleted_at": None})
        self.assertEqual(raised.exception.status_code, 404)

    def test_overdue_delete_moves_to_deleted(self) -> None:
        uid = self._create_user()
        t = self._create_todo(uid, due_date=(today_date() - timedelta(days=2)).isoformat())

        db = get_connection()
        try:
            delete_todo(t, db=db, user={"id": uid})
            res = get_trash("deleted", db=db, user={"id": uid})
        finally:
            db.close()

        self.assertEqual(res.deleted_count, 1)
        self.assertEqual([item.id for item in res.items], [t])
        self.assertEqual(res.overdue_count, 0)

    def test_cleanup_7day_window(self) -> None:
        import cleanup_overdue

        uid = self._create_user()
        now = now_shanghai()
        old_deleted = self._create_todo(uid)
        self._soft_delete(old_deleted, (now - timedelta(days=8)).isoformat(timespec="seconds"))
        new_deleted = self._create_todo(uid)
        self._soft_delete(new_deleted, (now - timedelta(days=6)).isoformat(timespec="seconds"))
        old_overdue = self._create_todo(uid, due_date=(today_date() - timedelta(days=8)).isoformat())
        new_overdue = self._create_todo(uid, due_date=(today_date() - timedelta(days=6)).isoformat())

        cleanup_overdue.main()

        db = get_connection()
        try:
            ids = {row["id"] for row in db.execute("SELECT id FROM todos").fetchall()}
        finally:
            db.close()

        self.assertNotIn(old_deleted, ids)
        self.assertIn(new_deleted, ids)
        self.assertNotIn(old_overdue, ids)
        self.assertIn(new_overdue, ids)


if __name__ == "__main__":
    unittest.main()
