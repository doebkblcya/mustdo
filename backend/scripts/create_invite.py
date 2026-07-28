"""创建邀请码。"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import get_connection, init_db  # noqa: E402
from app.security import generate_invite_code, hash_invite_code  # noqa: E402
from app.time_utils import utcish_now_iso  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="创建邀请码")
    parser.add_argument(
        "--type", default="single", choices=("single", "multi"),
        help="single=单次有效, multi=长期有效 (默认 single)",
    )
    parser.add_argument("--label", default=None, help="备注标签")
    args = parser.parse_args()

    init_db()
    code = generate_invite_code(args.type)

    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO invite_codes (code_hash, type, status, label, created_at)
                VALUES (?, ?, 'active', ?, ?)
                """,
                (hash_invite_code(code), args.type, args.label, utcish_now_iso()),
            )
            conn.commit()
    except Exception as exc:
        raise SystemExit(f"创建失败：{exc}")

    type_label = {"single": "单次", "multi": "长期"}[args.type]
    print(f"{code}  ({type_label})")


if __name__ == "__main__":
    main()
