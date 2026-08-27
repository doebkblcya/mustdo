from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from fastapi import HTTPException  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import get_connection, init_db  # noqa: E402
from app.schemas import ReminderUpsertRequest  # noqa: E402
from app.services.reminders import (  # noqa: E402
    cancel_reminder,
    fetch_due_pending,
    get_reminder,
    normalize_remind_at,
    upsert_reminder,
)
from app.services.scheduler import build_message_data, send_due_reminders_once  # noqa: E402
from app.services.subscribe import SubscribeSendError  # noqa: E402
from app.services.todos import list_grouped_todos, soft_delete_todo, update_todo  # noqa: E402
from app.time_utils import now_shanghai, today_date, utcish_now_iso  # noqa: E402

TEMPLATE_ID = "HWgp5u4Z_E3QD_vFMzHEZ3_gL0PDdsbtA5i7vjWQ9jc"


class ReminderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.env = patch.dict(
            os.environ,
            {
                "DATABASE_PATH": os.path.join(self.tmpdir.name, "test.db"),
                "SECRET_KEY": "test-secret",
                "WECHAT_TEMPLATE_ID": TEMPLATE_ID,
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

    # ---------- helpers ----------

    def _create_user(self, openid: str = "openid-reminder") -> int:
        now = now_shanghai().isoformat(timespec="seconds")
        db = get_connection()
        try:
            cursor = db.execute(
                """
                INSERT INTO users (wechat_openid, status, created_at, updated_at)
                VALUES (?, 'active', ?, ?)
                """,
                (openid, now, now),
            )
            db.commit()
            return int(cursor.lastrowid)
        finally:
            db.close()

    def _create_todo(self, user_id: int, due_time: str | None = "14:30") -> int:
        now = now_shanghai().isoformat(timespec="seconds")
        db = get_connection()
        try:
            cursor = db.execute(
                """
                INSERT INTO todos (user_id, content, due_date, due_time, status, created_at, updated_at)
                VALUES (?, '测试提醒', ?, ?, 'pending', ?, ?)
                """,
                (user_id, today_date().isoformat(), due_time, now, now),
            )
            db.commit()
            return int(cursor.lastrowid)
        finally:
            db.close()

    def _insert_reminder(self, user_id: int, todo_id: int, remind_at: str) -> None:
        db = get_connection()
        try:
            db.execute(
                """
                INSERT INTO todo_reminders (todo_id, user_id, remind_at, status, created_at, updated_at)
                VALUES (?, ?, ?, 'pending', ?, ?)
                """,
                (todo_id, user_id, remind_at, utcish_now_iso(), utcish_now_iso()),
            )
            db.commit()
        finally:
            db.close()

    # ---------- time normalization ----------

    def test_normalize_remind_at_naive_treated_as_local(self) -> None:
        self.assertEqual(
            normalize_remind_at(datetime(2026, 8, 25, 14, 30)),
            "2026-08-25T14:30:00+08:00",
        )

    def test_normalize_remind_at_converts_utc(self) -> None:
        self.assertEqual(
            normalize_remind_at(datetime(2026, 8, 25, 6, 30, tzinfo=timezone.utc)),
            "2026-08-25T14:30:00+08:00",
        )

    # ---------- upsert validation ----------

    def test_upsert_requires_due_time(self) -> None:
        user_id = self._create_user()
        todo_id = self._create_todo(user_id, due_time=None)
        db = get_connection()
        try:
            with self.assertRaises(HTTPException) as raised:
                upsert_reminder(db, user_id, todo_id, "2099-08-25T14:30:00+08:00")
        finally:
            db.close()
        self.assertEqual(raised.exception.detail["code"], "reminder_requires_time")

    def test_upsert_rejects_past(self) -> None:
        user_id = self._create_user()
        todo_id = self._create_todo(user_id)
        db = get_connection()
        try:
            with self.assertRaises(HTTPException) as raised:
                upsert_reminder(db, user_id, todo_id, "2020-01-01T00:00:00+08:00")
        finally:
            db.close()
        self.assertEqual(raised.exception.detail["code"], "reminder_time_in_past")

    def test_upsert_rejects_done_todo(self) -> None:
        user_id = self._create_user()
        todo_id = self._create_todo(user_id)
        db = get_connection()
        try:
            update_todo(db, user_id, todo_id, {"status": "done"})
            with self.assertRaises(HTTPException) as raised:
                upsert_reminder(db, user_id, todo_id, "2099-08-25T14:30:00+08:00")
        finally:
            db.close()
        self.assertEqual(raised.exception.detail["code"], "reminder_todo_done")

    def test_upsert_rejects_foreign_todo(self) -> None:
        other_user = self._create_user("openid-other")
        self._create_todo(other_user)
        user_id = self._create_user("openid-me")
        db = get_connection()
        try:
            with self.assertRaises(HTTPException) as raised:
                upsert_reminder(db, user_id, 1, "2099-08-25T14:30:00+08:00")
        finally:
            db.close()
        self.assertEqual(raised.exception.detail["code"], "todo_not_found")

    def test_upsert_creates_and_overwrites(self) -> None:
        user_id = self._create_user()
        todo_id = self._create_todo(user_id)
        db = get_connection()
        try:
            first = upsert_reminder(db, user_id, todo_id, "2099-08-25T14:30:00+08:00")
            self.assertEqual(first.status, "pending")
            second = upsert_reminder(db, user_id, todo_id, "2099-08-25T15:00:00+08:00")
            rows = db.execute("SELECT COUNT(*) AS count FROM todo_reminders").fetchone()["count"]
            self.assertEqual(rows, 1)
            self.assertEqual(second.remind_at, "2099-08-25T15:00:00+08:00")
        finally:
            db.close()

    def test_cancel_reminder_sets_cancelled(self) -> None:
        user_id = self._create_user()
        todo_id = self._create_todo(user_id)
        db = get_connection()
        try:
            upsert_reminder(db, user_id, todo_id, "2099-08-25T14:30:00+08:00")
            cancel_reminder(db, user_id, todo_id)
            self.assertIsNone(get_reminder(db, todo_id))
            status = db.execute(
                "SELECT status FROM todo_reminders WHERE todo_id = ?", (todo_id,)
            ).fetchone()["status"]
            self.assertEqual(status, "cancelled")
        finally:
            db.close()

    # ---------- summary + linkage ----------

    def test_list_includes_reminder_summary(self) -> None:
        user_id = self._create_user()
        todo_id = self._create_todo(user_id)
        db = get_connection()
        try:
            upsert_reminder(db, user_id, todo_id, "2099-08-25T14:30:00+08:00")
            groups = list_grouped_todos(db, user_id).groups
            todo = next(t for t in groups.today if t.id == todo_id)
            self.assertIsNotNone(todo.reminder)
            self.assertEqual(todo.reminder.remind_at, "2099-08-25T14:30:00+08:00")
            self.assertEqual(todo.reminder.status, "pending")
        finally:
            db.close()

    def test_patch_due_time_cancels_reminder(self) -> None:
        user_id = self._create_user()
        todo_id = self._create_todo(user_id)
        db = get_connection()
        try:
            upsert_reminder(db, user_id, todo_id, "2099-08-25T14:30:00+08:00")
            updated = update_todo(db, user_id, todo_id, {"due_time": "16:00"})
            self.assertIsNone(updated.reminder)
            status = db.execute(
                "SELECT status FROM todo_reminders WHERE todo_id = ?", (todo_id,)
            ).fetchone()["status"]
            self.assertEqual(status, "cancelled")
        finally:
            db.close()

    def test_patch_status_done_cancels_reminder(self) -> None:
        user_id = self._create_user()
        todo_id = self._create_todo(user_id)
        db = get_connection()
        try:
            upsert_reminder(db, user_id, todo_id, "2099-08-25T14:30:00+08:00")
            update_todo(db, user_id, todo_id, {"status": "done"})
            status = db.execute(
                "SELECT status FROM todo_reminders WHERE todo_id = ?", (todo_id,)
            ).fetchone()["status"]
            self.assertEqual(status, "cancelled")
        finally:
            db.close()

    def test_soft_delete_cancels_reminder(self) -> None:
        user_id = self._create_user()
        todo_id = self._create_todo(user_id)
        db = get_connection()
        try:
            upsert_reminder(db, user_id, todo_id, "2099-08-25T14:30:00+08:00")
            self.assertTrue(soft_delete_todo(db, user_id, todo_id))
            status = db.execute(
                "SELECT status FROM todo_reminders WHERE todo_id = ?", (todo_id,)
            ).fetchone()["status"]
            self.assertEqual(status, "cancelled")
        finally:
            db.close()

    # ---------- scheduler ----------

    def test_build_message_data_uses_template_fields(self) -> None:
        user_id = self._create_user()
        todo_id = self._create_todo(user_id)
        db = get_connection()
        try:
            self._insert_reminder(user_id, todo_id, "2020-01-01T00:00:00+08:00")
            row = fetch_due_pending(db, utcish_now_iso())[0]
            data = build_message_data(row)
        finally:
            db.close()
        # 模板字段 ID：thing1=事项主题、time2=事项时间；payload 必须与模板一一
        # 对应（用模板详情页的 {{thing1.DATA}}/{{time2.DATA}} 标识，而非中文标签）。
        self.assertEqual(data["thing1"]["value"], "测试提醒")
        self.assertEqual(data["time2"]["value"], f"14:30 {today_date().isoformat()}")
        self.assertEqual(set(data.keys()), {"thing1", "time2"})

    def test_fetch_due_pending_joins_openid(self) -> None:
        user_id = self._create_user("openid-due")
        todo_id = self._create_todo(user_id)
        future_todo_id = self._create_todo(user_id)
        db = get_connection()
        try:
            self._insert_reminder(user_id, todo_id, "2020-01-01T00:00:00+08:00")
            self._insert_reminder(user_id, future_todo_id, "2099-01-01T00:00:00+08:00")
            rows = fetch_due_pending(db, utcish_now_iso())
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["wechat_openid"], "openid-due")
            self.assertEqual(rows[0]["todo_id"], todo_id)
        finally:
            db.close()

    def test_send_marks_sent(self) -> None:
        user_id = self._create_user("openid-sent")
        todo_id = self._create_todo(user_id)
        db = get_connection()
        try:
            self._insert_reminder(user_id, todo_id, "2020-01-01T00:00:00+08:00")
            with patch(
                "app.services.scheduler.send_subscribe_message",
                new=AsyncMock(return_value=None),
            ) as send_mock:
                count = asyncio.run(send_due_reminders_once())
            row = db.execute(
                "SELECT status, sent_at FROM todo_reminders WHERE todo_id = ?", (todo_id,)
            ).fetchone()
        finally:
            db.close()
        self.assertEqual(count, 1)
        send_mock.assert_awaited_once()
        self.assertEqual(row["status"], "sent")
        self.assertIsNotNone(row["sent_at"])

    def test_send_failure_marks_failed_with_errcode(self) -> None:
        user_id = self._create_user("openid-fail")
        todo_id = self._create_todo(user_id)
        db = get_connection()
        try:
            self._insert_reminder(user_id, todo_id, "2020-01-01T00:00:00+08:00")
            with patch(
                "app.services.scheduler.send_subscribe_message",
                new=AsyncMock(side_effect=SubscribeSendError("43101", "user refuse")),
            ):
                count = asyncio.run(send_due_reminders_once())
            row = db.execute(
                "SELECT status, error_code FROM todo_reminders WHERE todo_id = ?", (todo_id,)
            ).fetchone()
        finally:
            db.close()
        self.assertEqual(count, 1)
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["error_code"], "43101")

    def test_send_skipped_when_template_missing_keeps_pending(self) -> None:
        user_id = self._create_user()
        todo_id = self._create_todo(user_id)
        db = get_connection()
        try:
            self._insert_reminder(user_id, todo_id, "2020-01-01T00:00:00+08:00")
            fake_settings = SimpleNamespace(wechat_template_id="")
            with patch("app.services.scheduler.get_settings", return_value=fake_settings):
                count = asyncio.run(send_due_reminders_once())
            status = db.execute(
                "SELECT status FROM todo_reminders WHERE todo_id = ?", (todo_id,)
            ).fetchone()["status"]
        finally:
            db.close()
        self.assertEqual(count, 0)
        self.assertEqual(status, "pending")


if __name__ == "__main__":
    unittest.main()
