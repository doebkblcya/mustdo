"""清空所有邀请码记录。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import get_connection, init_db  # noqa: E402


def main() -> None:
    init_db()
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM invite_codes")
        conn.commit()
        print(f"已删除 {cursor.rowcount} 条邀请码。")


if __name__ == "__main__":
    main()
