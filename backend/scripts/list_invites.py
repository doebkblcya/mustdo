"""列出所有邀请码。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import get_connection, init_db  # noqa: E402

TYPE_LABEL = {"single": "单次", "multi": "长期"}


def main() -> None:
    init_db()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, type, status, label, created_at, used_at, used_by_user_id
            FROM invite_codes
            ORDER BY id DESC
            """
        ).fetchall()

    if not rows:
        print("(空)")
        return

    for row in rows:
        parts = [
            f"[{row['id']}]",
            TYPE_LABEL.get(row["type"], row["type"]),
            _status_label(row["status"]),
        ]
        if row["label"]:
            parts.append(f"({row['label']})")
        parts.append(row["created_at"][:10])
        if row["used_at"]:
            parts.append(f"→ used by #{row['used_by_user_id']} {row['used_at'][:10]}")
        print("  ".join(parts))


def _status_label(status: str) -> str:
    return {"active": "有效", "redeemed": "已用", "revoked": "已禁用"}.get(status, status)


if __name__ == "__main__":
    main()
