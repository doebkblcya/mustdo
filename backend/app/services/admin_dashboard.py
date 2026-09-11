"""Read models for the human-oriented admin console.

The business API deliberately stays on native sqlite3.  These helpers follow
the same rule and return template-friendly dictionaries; SQLAlchemy/SQLAdmin
remain responsible only for the generic raw-data views and quota forms.
"""

from __future__ import annotations

import math
import sqlite3
from datetime import date, timedelta
from typing import Any

from app.time_utils import today_date

PAGE_SIZE = 20
ALLOWED_WINDOWS = (1, 7, 30, 0)


def normalize_days(raw: str | int | None, default: int = 7) -> int:
    try:
        value = int(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default
    return value if value in ALLOWED_WINDOWS else default


def mask_openid(value: str | None) -> str:
    if not value:
        return "—"
    if len(value) <= 10:
        return value
    return f"{value[:5]}…{value[-4:]}"


def _window(days: int) -> tuple[str | None, str, list[date]]:
    today = today_date()
    if days <= 0:
        chart_days = [today - timedelta(days=i) for i in range(29, -1, -1)]
        return None, "全部", chart_days
    start = today - timedelta(days=days - 1)
    chart_days = [start + timedelta(days=i) for i in range(days)]
    label = "今天" if days == 1 else f"近 {days} 天"
    return f"{start.isoformat()}T00:00:00", label, chart_days


def _where_since(column: str, since: str | None) -> tuple[str, list[Any]]:
    if since is None:
        return "", []
    return f" WHERE {column} >= ?", [since]


def collect_dashboard(db: sqlite3.Connection, days: int) -> dict[str, Any]:
    since, window_label, chart_days = _window(days)
    usage_where, usage_params = _where_since("created_at", since)
    reminder_created_where, reminder_created_params = _where_since("created_at", since)
    todo_where, todo_params = _where_since("created_at", since)

    users = db.execute(
        """
        SELECT COUNT(*) AS total,
               COALESCE(SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END), 0) AS enabled
        FROM users
        """
    ).fetchone()
    if since is None:
        active_users = db.execute(
            "SELECT COUNT(*) AS c FROM users WHERE last_login_at IS NOT NULL"
        ).fetchone()["c"]
    else:
        active_users = db.execute(
            "SELECT COUNT(*) AS c FROM users WHERE last_login_at >= ?", (since,)
        ).fetchone()["c"]

    asr = db.execute(
        f"""
        SELECT COUNT(*) AS calls,
               COALESCE(SUM(audio_seconds), 0) AS seconds,
               COALESCE(SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END), 0) AS success,
               COALESCE(SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END), 0) AS failed,
               COALESCE(CAST(AVG(duration_ms) AS INTEGER), 0) AS avg_ms
        FROM asr_usage{usage_where}
        """,
        usage_params,
    ).fetchone()
    ai = db.execute(
        f"""
        SELECT COUNT(*) AS calls,
               COALESCE(SUM(total_tokens), 0) AS tokens,
               COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
               COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
               COALESCE(SUM(CASE WHEN purpose = 'parse' THEN 1 ELSE 0 END), 0) AS parse_calls,
               COALESCE(SUM(CASE WHEN purpose = 'organize' THEN 1 ELSE 0 END), 0) AS organize_calls,
               COALESCE(SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END), 0) AS success,
               COALESCE(SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END), 0) AS failed,
               COALESCE(CAST(AVG(duration_ms) AS INTEGER), 0) AS avg_ms
        FROM ai_usage{usage_where}
        """,
        usage_params,
    ).fetchone()
    reminders = db.execute(
        f"""
        SELECT COUNT(*) AS created,
               COALESCE(SUM(CASE WHEN status = 'sent' THEN 1 ELSE 0 END), 0) AS sent,
               COALESCE(SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END), 0) AS failed,
               COALESCE(SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END), 0) AS pending
        FROM todo_reminders{reminder_created_where}
        """,
        reminder_created_params,
    ).fetchone()
    todos = db.execute(
        f"""
        SELECT COUNT(*) AS created,
               COALESCE(SUM(CASE WHEN status = 'pending' AND deleted_at IS NULL THEN 1 ELSE 0 END), 0) AS pending,
               COALESCE(SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END), 0) AS done
        FROM todos{todo_where}
        """,
        todo_params,
    ).fetchone()

    trend_since = f"{chart_days[0].isoformat()}T00:00:00"
    trend: dict[str, dict[str, Any]] = {
        d.isoformat(): {"day": d.isoformat(), "asr_seconds": 0.0, "ai_tokens": 0, "calls": 0}
        for d in chart_days
    }
    for row in db.execute(
        """
        SELECT substr(created_at, 1, 10) AS day,
               COALESCE(SUM(audio_seconds), 0) AS seconds,
               COUNT(*) AS calls
        FROM asr_usage WHERE created_at >= ? GROUP BY day
        """,
        (trend_since,),
    ).fetchall():
        if row["day"] in trend:
            trend[row["day"]]["asr_seconds"] = round(float(row["seconds"]), 1)
            trend[row["day"]]["calls"] += int(row["calls"])
    for row in db.execute(
        """
        SELECT substr(created_at, 1, 10) AS day,
               COALESCE(SUM(total_tokens), 0) AS tokens,
               COUNT(*) AS calls
        FROM ai_usage WHERE created_at >= ? GROUP BY day
        """,
        (trend_since,),
    ).fetchall():
        if row["day"] in trend:
            trend[row["day"]]["ai_tokens"] = int(row["tokens"])
            trend[row["day"]]["calls"] += int(row["calls"])

    top_users = _top_users(db, since)
    quota_alerts = _quota_alerts(db)
    failures = [
        {
            **dict(row),
            "openid_masked": mask_openid(row["wechat_openid"]),
            "error_label": reminder_error_label(row["error_code"]),
        }
        for row in db.execute(
            """
            SELECT r.id, r.user_id, r.error_code, r.updated_at,
                   u.wechat_openid, t.content
            FROM todo_reminders r
            JOIN users u ON u.id = r.user_id
            JOIN todos t ON t.id = r.todo_id
            WHERE r.status = 'failed'
            ORDER BY r.updated_at DESC LIMIT 6
            """
        ).fetchall()
    ]

    total_calls = int(asr["calls"]) + int(ai["calls"])
    successful_calls = int(asr["success"]) + int(ai["success"])
    return {
        "days": days,
        "window_label": window_label,
        "users": {
            "total": int(users["total"]),
            "enabled": int(users["enabled"]),
            "active": int(active_users),
        },
        "asr": dict(asr),
        "ai": dict(ai),
        "reminders": dict(reminders),
        "todos": dict(todos),
        "success_rate": round(successful_calls * 100 / total_calls, 1) if total_calls else None,
        "trend": list(trend.values()),
        "trend_asr_max": max((float(v["asr_seconds"]) for v in trend.values()), default=0) or 1,
        "trend_ai_max": max((int(v["ai_tokens"]) for v in trend.values()), default=0) or 1,
        "top_users": top_users,
        "quota_alerts": quota_alerts,
        "failures": failures,
    }


def _top_users(db: sqlite3.Connection, since: str | None) -> list[dict[str, Any]]:
    condition = "" if since is None else "AND created_at >= ?"
    params: list[Any] = [] if since is None else [since, since]
    rows = db.execute(
        f"""
        SELECT u.id AS user_id, u.wechat_openid,
               COALESCE(a.seconds, 0) AS asr_seconds,
               COALESCE(i.tokens, 0) AS ai_tokens,
               COALESCE(a.calls, 0) + COALESCE(i.calls, 0) AS calls
        FROM users u
        LEFT JOIN (
            SELECT user_id, SUM(audio_seconds) AS seconds, COUNT(*) AS calls
            FROM asr_usage WHERE 1=1 {condition} GROUP BY user_id
        ) a ON a.user_id = u.id
        LEFT JOIN (
            SELECT user_id, SUM(total_tokens) AS tokens, COUNT(*) AS calls
            FROM ai_usage WHERE 1=1 {condition} GROUP BY user_id
        ) i ON i.user_id = u.id
        WHERE COALESCE(a.calls, 0) + COALESCE(i.calls, 0) > 0
        ORDER BY calls DESC, ai_tokens DESC, u.id ASC LIMIT 6
        """,
        params,
    ).fetchall()
    return [{**dict(row), "openid_masked": mask_openid(row["wechat_openid"])} for row in rows]


def _quota_alerts(db: sqlite3.Connection) -> list[dict[str, Any]]:
    day_start = f"{today_date().isoformat()}T00:00:00"
    rows = db.execute(
        """
        WITH a AS (
            SELECT user_id, SUM(audio_seconds) AS used FROM asr_usage
            WHERE created_at >= ? GROUP BY user_id
        ), i AS (
            SELECT user_id, SUM(total_tokens) AS used FROM ai_usage
            WHERE created_at >= ? GROUP BY user_id
        )
        SELECT u.id AS user_id, u.wechat_openid,
               q.asr_daily_seconds, q.ai_daily_tokens,
               COALESCE(a.used, 0) AS asr_used, COALESCE(i.used, 0) AS ai_used
        FROM user_quotas q
        JOIN users u ON u.id = q.user_id
        LEFT JOIN a ON a.user_id = q.user_id
        LEFT JOIN i ON i.user_id = q.user_id
        WHERE (q.asr_daily_seconds > 0 AND COALESCE(a.used, 0) >= q.asr_daily_seconds * 0.8)
           OR (q.ai_daily_tokens > 0 AND COALESCE(i.used, 0) >= q.ai_daily_tokens * 0.8)
        ORDER BY MAX(
            CASE WHEN q.asr_daily_seconds > 0 THEN COALESCE(a.used, 0) / q.asr_daily_seconds ELSE 0 END,
            CASE WHEN q.ai_daily_tokens > 0 THEN CAST(COALESCE(i.used, 0) AS REAL) / q.ai_daily_tokens ELSE 0 END
        ) DESC
        LIMIT 6
        """,
        (day_start, day_start),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["openid_masked"] = mask_openid(row["wechat_openid"])
        item["asr_ratio"] = _ratio(row["asr_used"], row["asr_daily_seconds"])
        item["ai_ratio"] = _ratio(row["ai_used"], row["ai_daily_tokens"])
        item["max_ratio"] = max(item["asr_ratio"], item["ai_ratio"])
        result.append(item)
    return result


def _ratio(used: float, limit: float) -> int:
    if not limit or float(limit) <= 0:
        return 0
    return min(100, round(float(used) * 100 / float(limit)))


_USER_SORTS = {
    "id": "user_id ASC",
    "created": "created_at DESC",
    "active": "last_login_at IS NULL ASC, last_login_at DESC",
    "asr": "asr_used DESC, user_id ASC",
    "ai": "ai_used DESC, user_id ASC",
    "todos": "todo_total DESC, user_id ASC",
}


def list_users(
    db: sqlite3.Connection,
    *,
    query: str = "",
    status: str = "all",
    usage: str = "all",
    sort: str = "active",
    page: int = 1,
) -> dict[str, Any]:
    page = max(1, page)
    status = status if status in ("all", "active", "disabled") else "all"
    usage = usage if usage in ("all", "today", "near") else "all"
    sort = sort if sort in _USER_SORTS else "active"
    day_start = f"{today_date().isoformat()}T00:00:00"

    filters: list[str] = []
    params: list[Any] = [day_start, day_start, day_start]
    query = query.strip()
    if query:
        filters.append("(wechat_openid LIKE ? OR CAST(user_id AS TEXT) LIKE ?)")
        term = f"%{query}%"
        params.extend((term, term))
    if status != "all":
        filters.append("status = ?")
        params.append(status)
    if usage == "today":
        filters.append("(asr_calls > 0 OR ai_calls > 0)")
    elif usage == "near":
        filters.append(
            "((asr_limit > 0 AND asr_used >= asr_limit * 0.8)"
            " OR (ai_limit > 0 AND ai_used >= ai_limit * 0.8))"
        )
    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    base = _user_listing_sql()
    count = int(db.execute(f"SELECT COUNT(*) AS c FROM ({base}) b {where}", params).fetchone()["c"])
    total_pages = max(1, math.ceil(count / PAGE_SIZE))
    page = min(page, total_pages)
    rows = db.execute(
        f"SELECT * FROM ({base}) b {where} ORDER BY {_USER_SORTS[sort]} LIMIT ? OFFSET ?",
        (*params, PAGE_SIZE, (page - 1) * PAGE_SIZE),
    ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["openid_masked"] = mask_openid(row["wechat_openid"])
        item["asr_ratio"] = _ratio(row["asr_used"], row["asr_limit"])
        item["ai_ratio"] = _ratio(row["ai_used"], row["ai_limit"])
        items.append(item)
    return {
        "items": items,
        "count": count,
        "page": page,
        "pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
        "query": query,
        "status": status,
        "usage": usage,
        "sort": sort,
    }


def _user_listing_sql() -> str:
    return """
        WITH a AS (
            SELECT user_id, SUM(audio_seconds) AS used, COUNT(*) AS calls
            FROM asr_usage WHERE created_at >= ? GROUP BY user_id
        ), i AS (
            SELECT user_id, SUM(total_tokens) AS used, COUNT(*) AS calls
            FROM ai_usage WHERE created_at >= ? GROUP BY user_id
        ), r AS (
            SELECT user_id,
                   SUM(CASE WHEN status = 'sent' THEN 1 ELSE 0 END) AS sent,
                   SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed
            FROM todo_reminders WHERE created_at >= ? GROUP BY user_id
        ), t AS (
            SELECT user_id, COUNT(*) AS total,
                   SUM(CASE WHEN status = 'pending' AND deleted_at IS NULL THEN 1 ELSE 0 END) AS pending
            FROM todos GROUP BY user_id
        )
        SELECT u.id AS user_id, u.wechat_openid, u.status, u.created_at, u.last_login_at,
               q.id AS quota_id, COALESCE(q.asr_enabled, 1) AS asr_enabled,
               COALESCE(q.asr_daily_seconds, 0) AS asr_limit,
               COALESCE(q.ai_enabled, 1) AS ai_enabled,
               COALESCE(q.ai_daily_tokens, 0) AS ai_limit,
               COALESCE(a.used, 0) AS asr_used, COALESCE(a.calls, 0) AS asr_calls,
               COALESCE(i.used, 0) AS ai_used, COALESCE(i.calls, 0) AS ai_calls,
               COALESCE(r.sent, 0) AS reminder_sent, COALESCE(r.failed, 0) AS reminder_failed,
               COALESCE(t.total, 0) AS todo_total, COALESCE(t.pending, 0) AS todo_pending
        FROM users u
        LEFT JOIN user_quotas q ON q.user_id = u.id
        LEFT JOIN a ON a.user_id = u.id
        LEFT JOIN i ON i.user_id = u.id
        LEFT JOIN r ON r.user_id = u.id
        LEFT JOIN t ON t.user_id = u.id
    """


def get_user_detail(db: sqlite3.Connection, user_id: int, days: int) -> dict[str, Any] | None:
    from app.services.usage_history import collect_user_usage

    row = db.execute(
        """
        SELECT u.*, q.id AS quota_id, COALESCE(q.asr_enabled, 1) AS asr_enabled,
               COALESCE(q.asr_daily_seconds, 0) AS asr_limit,
               COALESCE(q.ai_enabled, 1) AS ai_enabled,
               COALESCE(q.ai_daily_tokens, 0) AS ai_limit,
               q.updated_at AS quota_updated_at
        FROM users u LEFT JOIN user_quotas q ON q.user_id = u.id
        WHERE u.id = ?
        """,
        (user_id,),
    ).fetchone()
    if row is None:
        return None
    user = dict(row)
    user["openid_masked"] = mask_openid(row["wechat_openid"])
    usage = collect_user_usage(db, user_id, days)
    today_listing = list_users(db, query=str(user_id), sort="id")
    today = next((item for item in today_listing["items"] if item["user_id"] == user_id), None)

    todos = [
        dict(item)
        for item in db.execute(
            """
        SELECT id, content, due_date, due_time, status, pinned, deleted_at, updated_at
        FROM todos WHERE user_id = ?
        ORDER BY updated_at DESC LIMIT 30
        """,
            (user_id,),
        ).fetchall()
    ]
    reminders = []
    for item in db.execute(
        """
        SELECT r.id, r.remind_at, r.status, r.sent_at, r.error_code, r.updated_at,
               t.id AS todo_id, t.content
        FROM todo_reminders r JOIN todos t ON t.id = r.todo_id
        WHERE r.user_id = ? ORDER BY r.updated_at DESC LIMIT 30
        """,
        (user_id,),
    ).fetchall():
        mapped = dict(item)
        mapped["error_label"] = reminder_error_label(item["error_code"])
        reminders.append(mapped)
    audits = [
        dict(item)
        for item in db.execute(
            """
        SELECT username, action, target_type, target_id, detail, created_at
        FROM admin_audit_logs
        WHERE (target_type IN ('user-quota', 'user_quotas') AND target_id = ?)
           OR detail LIKE ?
        ORDER BY created_at DESC LIMIT 10
        """,
            (str(user.get("quota_id") or ""), f'%"user_id": {user_id}%'),
        ).fetchall()
    ]
    return {
        "user": user,
        "today": today,
        "usage": usage,
        "todos": todos,
        "reminders": reminders,
        "audits": audits,
        "days": days,
    }


def list_diagnostics(
    db: sqlite3.Connection,
    *,
    kind: str,
    query: str,
    status: str,
    page: int,
) -> dict[str, Any]:
    kind = kind if kind in ("reminders", "todos") else "reminders"
    page = max(1, page)
    query = query.strip()
    if kind == "reminders":
        allowed = ("all", "pending", "sent", "failed", "cancelled")
        status = status if status in allowed else "all"
        filters, params = [], []
        if query:
            filters.append(
                "(t.content LIKE ? OR u.wechat_openid LIKE ? OR CAST(r.user_id AS TEXT) LIKE ?)"
            )
            term = f"%{query}%"
            params.extend((term, term, term))
        if status != "all":
            filters.append("r.status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        count = int(
            db.execute(
                f"SELECT COUNT(*) AS c FROM todo_reminders r JOIN todos t ON t.id=r.todo_id JOIN users u ON u.id=r.user_id {where}",
                params,
            ).fetchone()["c"]
        )
        pages = max(1, math.ceil(count / PAGE_SIZE))
        page = min(page, pages)
        rows = db.execute(
            f"""
            SELECT r.id, r.user_id, r.remind_at, r.status, r.sent_at, r.error_code,
                   r.updated_at, t.id AS todo_id, t.content, u.wechat_openid
            FROM todo_reminders r JOIN todos t ON t.id=r.todo_id
            JOIN users u ON u.id=r.user_id {where}
            ORDER BY r.updated_at DESC LIMIT ? OFFSET ?
            """,
            (*params, PAGE_SIZE, (page - 1) * PAGE_SIZE),
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["openid_masked"] = mask_openid(row["wechat_openid"])
            item["error_label"] = reminder_error_label(row["error_code"])
            items.append(item)
    else:
        allowed = ("all", "pending", "done", "deleted")
        status = status if status in allowed else "all"
        filters, params = [], []
        if query:
            filters.append(
                "(t.content LIKE ? OR u.wechat_openid LIKE ? OR CAST(t.user_id AS TEXT) LIKE ?)"
            )
            term = f"%{query}%"
            params.extend((term, term, term))
        if status == "deleted":
            filters.append("t.deleted_at IS NOT NULL")
        elif status != "all":
            filters.append("t.status = ? AND t.deleted_at IS NULL")
            params.append(status)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        count = int(
            db.execute(
                f"SELECT COUNT(*) AS c FROM todos t JOIN users u ON u.id=t.user_id {where}", params
            ).fetchone()["c"]
        )
        pages = max(1, math.ceil(count / PAGE_SIZE))
        page = min(page, pages)
        rows = db.execute(
            f"""
            SELECT t.id, t.user_id, t.content, t.due_date, t.due_time, t.status,
                   t.pinned, t.deleted_at, t.updated_at, u.wechat_openid,
                   r.status AS reminder_status
            FROM todos t JOIN users u ON u.id=t.user_id
            LEFT JOIN todo_reminders r ON r.todo_id=t.id {where}
            ORDER BY t.updated_at DESC LIMIT ? OFFSET ?
            """,
            (*params, PAGE_SIZE, (page - 1) * PAGE_SIZE),
        ).fetchall()
        items = [{**dict(row), "openid_masked": mask_openid(row["wechat_openid"])} for row in rows]

    return {
        "kind": kind,
        "items": items,
        "count": count,
        "page": page,
        "pages": pages,
        "has_prev": page > 1,
        "has_next": page < pages,
        "query": query,
        "status": status,
    }


def reminder_error_label(code: str | None) -> str:
    if not code:
        return "—"
    labels = {
        "43101": "用户拒绝接收消息",
        "47003": "模板参数不符合要求",
        "40037": "模板 ID 无效",
        "41030": "页面路径不合法",
        "42001": "微信凭证已过期",
        "45009": "接口调用达到上限",
    }
    return labels.get(str(code), f"微信错误码 {code}")
