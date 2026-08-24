from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import get_connection, init_db  # noqa: E402
from app.time_utils import now_shanghai, today_date  # noqa: E402


def main() -> None:
    init_db()
    # 软删超过 7 天:阈值用"时间戳"(deleted_at 存的是 ISO 秒级时间)
    cutoff_time = (now_shanghai() - timedelta(days=7)).isoformat(timespec="seconds")
    # 截止日期超过 7 天:阈值用"日期"(due_date 存的是 YYYY-MM-DD)
    cutoff_date = (today_date() - timedelta(days=7)).isoformat()

    with get_connection() as conn:
        # ① 用户主动删除(软删)超过 7 天 → 清空回收站
        trashed = conn.execute(
            """
            DELETE FROM todos
            WHERE deleted_at IS NOT NULL
              AND deleted_at < ?
            """,
            (cutoff_time,),
        ).rowcount
        # ② 未软删、截止日期超过 7 天 → 逾期清理(pending 与 done 一并处理)
        overdue = conn.execute(
            """
            DELETE FROM todos
            WHERE deleted_at IS NULL
              AND due_date < ?
            """,
            (cutoff_date,),
        ).rowcount
        # 两条 DELETE 在上方同一事务内执行,一次 commit 一起生效
        conn.commit()

    print(f"Deleted {trashed} trashed todo(s).")
    print(f"Deleted {overdue} overdue todo(s).")


if __name__ == "__main__":
    main()
