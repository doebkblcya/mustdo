from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.db import get_connection, init_db  # noqa: E402
from app.security import generate_invite_code, hash_invite_code  # noqa: E402
from app.time_utils import utcish_now_iso  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a single-use invite code.")
    parser.add_argument("--label", default=None, help="Optional note for this invite.")
    args = parser.parse_args()

    init_db()
    code = generate_invite_code()
    try:
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO invite_codes (code_hash, status, label, created_at)
                VALUES (?, 'active', ?, ?)
                """,
                (hash_invite_code(code), args.label, utcish_now_iso()),
            )
            conn.commit()
            invite_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        raise SystemExit("Invite collision. Run the command again.")

    settings = get_settings()
    print("Invite code created.")
    print(f"Code: {code}")
    print(f"Database: {settings.database_path}")
    print(f"Row: id={invite_id}, status=active, label={args.label or ''}")
    print("Save the code now. The database stores only code_hash, not the plaintext code.")
    if settings.secret_key in {"dev-secret-change-me", "change-me", "change-me-in-production"}:
        print("Warning: SECRET_KEY is still a default value. Set a stable SECRET_KEY before issuing real invites.")


if __name__ == "__main__":
    main()
