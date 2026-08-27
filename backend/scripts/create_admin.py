"""Create or update an admin account for the Mustdo console.

Usage:
    python -m scripts.create_admin --username <name> [--password <pw>]

If the admin exists, the password is reset (and ``session_version`` bumped,
which invalidates every existing session for that admin). If it doesn't exist,
a new admin is created.

Password is read from ``--password`` or ``ADMIN_PASSWORD`` env var. If neither
is provided and stdin is a TTY, you'll be prompted interactively. Prefer using
the env var or a secret manager.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.admin_security import hash_password
from app.db import get_connection, init_db
from app.time_utils import utcish_now_iso


def _normalize(username: str) -> str:
    return username.strip().lower()


def main() -> int:
    parser = argparse.ArgumentParser(description="Create/update an admin account")
    parser.add_argument("--username", required=True, help="管理员用户名")
    parser.add_argument("--password", help="密码（缺省读 ADMIN_PASSWORD 或交互输入）")
    args = parser.parse_args()

    username = args.username.strip()
    if not username:
        print("用户名不能为空", file=sys.stderr)
        return 1

    password = args.password or os.getenv("ADMIN_PASSWORD")
    if not password:
        if not sys.stdin.isatty():
            print("缺少密码：请用 --password 或 ADMIN_PASSWORD", file=sys.stderr)
            return 1
        password = getpass.getpass("输入密码: ")

    if not password or len(password) < 8:
        print("密码太短（至少 8 位）", file=sys.stderr)
        return 1

    init_db()
    normalized = _normalize(username)
    password_hash = hash_password(password)
    now = utcish_now_iso()

    with get_connection() as db:
        row = db.execute(
            "SELECT id FROM admins WHERE username_normalized = ?",
            (normalized,),
        ).fetchone()
        if row is None:
            db.execute(
                """
                INSERT INTO admins
                    (username, username_normalized, password_hash, session_version,
                     status, created_at, updated_at)
                VALUES (?, ?, ?, 1, 'active', ?, ?)
                """,
                (username, normalized, password_hash, now, now),
            )
            print(f"创建管理员：{username}")
        else:
            admin_id = int(row["id"])
            # Bump session_version so any existing sessions for this admin are invalidated.
            db.execute(
                """
                UPDATE admins
                SET password_hash = ?, session_version = session_version + 1,
                    status = 'active', updated_at = ?
                WHERE id = ?
                """,
                (password_hash, now, admin_id),
            )
            print(f"重置密码（并使其旧会话失效）：{username}")
        db.commit()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
