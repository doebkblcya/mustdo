"""Per-user historical ASR/AI usage aggregation for the admin console.

Runs over a native ``sqlite3.Connection`` (same metering tables the business
API writes). A user + time-window in, aggregated ASR/AI stats + a per-day
breakdown out. No new tables; "today" is the Shanghai calendar day.
"""

from __future__ import annotations

import sqlite3
from datetime import timedelta

from app.time_utils import now_shanghai


def _day_start() -> str:
    return f"{now_shanghai().date().isoformat()}T00:00:00"


def _since_iso(days: int) -> str:
    return (now_shanghai() - timedelta(days=days)).isoformat(timespec="seconds")


def collect_user_usage(
    db: sqlite3.Connection,
    user_id: int,
    days: int | None,
) -> dict[str, object]:
    """Aggregate one user's ASR/AI usage over the window.

    ``days`` semantics: 1 = today, N = last N days, 0/None = all time.
    Returns a dict with user info, aggregated ASR/AI stats and a per-day
    breakdown; asr/ai are None when the user does not exist.
    """
    user = db.execute(
        "SELECT id, wechat_openid, status FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if user is None:
        return {"user_id": user_id, "openid": None, "days": days, "asr": None, "ai": [], "per_day": []}

    if days is None or days <= 0:
        since = None
        since_label = "全部"
    else:
        since = _day_start() if days == 1 else _since_iso(days)
        since_label = "今天" if days == 1 else f"近 {days} 天"

    where, params = "WHERE user_id = ?", [user_id]
    if since is not None:
        where += " AND created_at >= ?"
        params.append(since)

    asr = db.execute(
        f"""
        SELECT COUNT(*) AS calls,
               COALESCE(SUM(audio_seconds), 0) AS seconds,
               COALESCE(SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END), 0) AS success,
               COALESCE(SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END), 0) AS failed,
               COALESCE(CAST(AVG(duration_ms) AS INTEGER), 0) AS avg_ms
        FROM asr_usage {where}
        """,
        params,
    ).fetchone()

    ai = db.execute(
        f"""
        SELECT purpose,
               COUNT(*) AS calls,
               COALESCE(SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END), 0) AS success,
               COALESCE(SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END), 0) AS failed,
               COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
               COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
               COALESCE(SUM(total_tokens), 0) AS total_tokens
        FROM ai_usage {where}
        GROUP BY purpose
        ORDER BY purpose
        """,
        params,
    ).fetchall()

    asr_day = {
        r["day"]: r
        for r in db.execute(
            f"""
            SELECT substr(created_at, 1, 10) AS day,
                   COUNT(*) AS calls,
                   COALESCE(SUM(audio_seconds), 0) AS seconds
            FROM asr_usage {where}
            GROUP BY day
            """,
            params,
        ).fetchall()
    }
    ai_day = {
        r["day"]: r
        for r in db.execute(
            f"""
            SELECT substr(created_at, 1, 10) AS day,
                   COUNT(*) AS calls,
                   COALESCE(SUM(total_tokens), 0) AS tokens
            FROM ai_usage {where}
            GROUP BY day
            """,
            params,
        ).fetchall()
    }
    per_day = [
        {
            "day": day,
            "asr_calls": int(asr_day[day]["calls"]) if day in asr_day else 0,
            "asr_seconds": float(asr_day[day]["seconds"]) if day in asr_day else 0.0,
            "ai_calls": int(ai_day[day]["calls"]) if day in ai_day else 0,
            "ai_tokens": int(ai_day[day]["tokens"]) if day in ai_day else 0,
        }
        for day in sorted(set(asr_day) | set(ai_day), reverse=True)
    ]

    return {
        "user_id": user_id,
        "openid": user["wechat_openid"],
        "days": days,
        "since_label": since_label,
        "asr": {
            "calls": int(asr["calls"]),
            "seconds": float(asr["seconds"]),
            "success": int(asr["success"]),
            "failed": int(asr["failed"]),
            "avg_ms": int(asr["avg_ms"]),
        },
        "ai": [
            {
                "purpose": r["purpose"],
                "calls": int(r["calls"]),
                "success": int(r["success"]),
                "failed": int(r["failed"]),
                "prompt_tokens": int(r["prompt_tokens"]),
                "completion_tokens": int(r["completion_tokens"]),
                "total_tokens": int(r["total_tokens"]),
            }
            for r in ai
        ],
        "per_day": per_day,
    }
