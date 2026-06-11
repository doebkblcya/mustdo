from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.db import get_connection, init_db  # noqa: E402


def main() -> None:
    init_db()
    settings = get_settings()
    print(f"Database: {settings.database_path}")
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, status, label, created_at, used_at, used_by_user_id
            FROM invite_codes
            ORDER BY id DESC
            """
        ).fetchall()

    if not rows:
        print("No invite codes.")
        return

    print("id\tstatus\tlabel\tcreated_at\tused_at\tused_by_user_id")
    for row in rows:
        print(
            "{}\t{}\t{}\t{}\t{}\t{}".format(
                row["id"],
                row["status"],
                row["label"] or "",
                row["created_at"],
                row["used_at"] or "",
                row["used_by_user_id"] or "",
            )
        )


if __name__ == "__main__":
    main()
