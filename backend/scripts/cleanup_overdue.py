from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import get_connection, init_db  # noqa: E402
from app.time_utils import today_date  # noqa: E402


def main() -> None:
    init_db()
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM todos WHERE due_date < ?",
            (today_date().isoformat(),),
        )
        conn.commit()
        deleted = cursor.rowcount
    print(f"Deleted {deleted} overdue todo(s).")


if __name__ == "__main__":
    main()
