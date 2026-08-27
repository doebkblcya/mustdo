"""Read-only aggregation for the admin usage-summary page.

Runs over a native ``sqlite3.Connection`` (consistent with the business API and
the rest of the metering path). Semantics mirror ``quota.py``: a limit of 0
means unlimited; the day is the Shanghai calendar day.
"""

from __future__ import annotations

import sqlite3

from app.time_utils import today_date


def _day_start() -> str:
    return f"{today_date().isoformat()}T00:00:00"


def collect_usage_summary(db: sqlite3.Connection) -> list[dict[str, object]]:
    """One row per user with today's ASR/AI usage, limit and remaining.

    Returns rows covering every user that has a quota row, is active, or has any
    usage today. Users with no quota and no usage are omitted (the page lists
    users you actually manage).
    """
    day_start = _day_start()

    users = db.execute(
        """
        SELECT u.id, u.wechat_openid, u.status
        FROM users u
        LEFT JOIN user_quotas q ON q.user_id = u.id
        WHERE u.status = 'active'
          AND (
            q.user_id IS NOT NULL
            OR EXISTS (SELECT 1 FROM asr_usage a WHERE a.user_id = u.id AND a.created_at >= ?)
            OR EXISTS (SELECT 1 FROM ai_usage a WHERE a.user_id = u.id AND a.created_at >= ?)
            OR EXISTS (SELECT 1 FROM todo_reminders r WHERE r.user_id = u.id AND r.created_at >= ?)
          )
        ORDER BY u.id
        """,
        (day_start, day_start, day_start),
    ).fetchall()

    asr_today = {
        int(r["user_id"]): r
        for r in db.execute(
            """
            SELECT user_id,
                   COALESCE(SUM(audio_seconds), 0) AS used_seconds,
                   COUNT(*) AS calls,
                   SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS success
            FROM asr_usage
            WHERE created_at >= ?
            GROUP BY user_id
            """,
            (day_start,),
        ).fetchall()
    }
    ai_today = {
        int(r["user_id"]): r
        for r in db.execute(
            """
            SELECT user_id,
                   COALESCE(SUM(total_tokens), 0) AS used_tokens,
                   COUNT(*) AS calls,
                   SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS success
            FROM ai_usage
            WHERE created_at >= ?
            GROUP BY user_id
            """,
            (day_start,),
        ).fetchall()
    }
    reminder_today = {
        int(r["user_id"]): r
        for r in db.execute(
            """
            SELECT user_id,
                   COALESCE(SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END), 0) AS created_today,
                   COALESCE(SUM(CASE WHEN status = 'sent' AND sent_at >= ? THEN 1 ELSE 0 END), 0) AS sent_today,
                   COALESCE(SUM(CASE WHEN status = 'failed' AND updated_at >= ? THEN 1 ELSE 0 END), 0) AS failed_today
            FROM todo_reminders
            GROUP BY user_id
            """,
            (day_start, day_start, day_start),
        ).fetchall()
    }
    quotas = {
        int(r["user_id"]): r
        for r in db.execute("SELECT * FROM user_quotas").fetchall()
    }

    rows: list[dict[str, object]] = []
    for user in users:
        uid = int(user["id"])
        quota = quotas.get(uid)
        asr = asr_today.get(uid)
        ai = ai_today.get(uid)
        rem = reminder_today.get(uid)

        asr_limit = float(quota["asr_daily_seconds"]) if quota else 0.0
        ai_limit = int(quota["ai_daily_tokens"]) if quota else 0
        asr_used = float(asr["used_seconds"]) if asr else 0.0
        ai_used = int(ai["used_tokens"]) if ai else 0

        rows.append(
            {
                "user_id": uid,
                "openid": user["wechat_openid"],
                "status": user["status"],
                "asr_enabled": bool(quota["asr_enabled"]) if quota else True,
                "asr_used_seconds": asr_used,
                "asr_limit": asr_limit,
                "asr_calls": int(asr["calls"]) if asr else 0,
                "asr_success": int(asr["success"]) if asr else 0,
                "ai_enabled": bool(quota["ai_enabled"]) if quota else True,
                "ai_used_tokens": ai_used,
                "ai_limit": ai_limit,
                "ai_calls": int(ai["calls"]) if ai else 0,
                "ai_success": int(ai["success"]) if ai else 0,
                "reminder_created": int(rem["created_today"]) if rem else 0,
                "reminder_sent": int(rem["sent_today"]) if rem else 0,
                "reminder_failed": int(rem["failed_today"]) if rem else 0,
            }
        )

    return rows
