"""Per-user ASR/AI permission, total-quota enforcement and usage metering.

Everything here runs over a native ``sqlite3.Connection`` (the same one the
business API uses) so the admin console and the runtime share one source of
truth without pulling an ORM into the request path.

Limit semantics
---------------
- Every user receives a quota row at account creation. ``get_quota`` still
  repairs a missing row defensively using the configured public defaults.
- ``asr_total_seconds`` / ``ai_total_tokens`` of 0 mean "no cap".
- ``*_enabled`` = 0 means the service is refused for that user.

Enforcement rules (matching the product decision)
-------------------------------------------------
ASR: ``total_used_seconds + this_audio_seconds > limit`` -> refuse the call
     BEFORE anything is sent upstream. Format/length errors short-circuit
     earlier in ``read_upload_as_pcm`` and never consume quota.
AI:  ``total_used_tokens >= limit`` -> refuse to start the call. This is a
     soft cap: a call that starts may push cumulative tokens past the limit;
     the NEXT call is then refused.
"""

from __future__ import annotations

import sqlite3

from app.config import get_settings
from app.errors import raise_api_error
from app.time_utils import utcish_now_iso

# Error codes surfaced to the mini-program (stable machine codes).
CODE_ASR_DISABLED = "asr_disabled"
CODE_AI_DISABLED = "ai_disabled"
CODE_ASR_QUOTA_EXCEEDED = "asr_quota_exceeded"
CODE_AI_QUOTA_EXCEEDED = "ai_quota_exceeded"


def get_quota(db: sqlite3.Connection, user_id: int) -> sqlite3.Row:
    """Return the user's quota row, repairing a missing default if needed."""
    row = db.execute(
        "SELECT * FROM user_quotas WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if row is not None:
        return row

    create_default_quota(db, user_id)
    db.commit()
    return db.execute(
        "SELECT * FROM user_quotas WHERE user_id = ?",
        (user_id,),
    ).fetchone()


def create_default_quota(db: sqlite3.Connection, user_id: int) -> None:
    """Insert the configured default quota without committing the transaction."""
    settings = get_settings()
    now = utcish_now_iso()
    db.execute(
        """
        INSERT OR IGNORE INTO user_quotas
            (user_id, asr_enabled, asr_total_seconds, ai_enabled,
             ai_total_tokens, created_at, updated_at)
        VALUES (?, 1, ?, 1, ?, ?, ?)
        """,
        (
            user_id,
            max(0.0, settings.default_asr_total_seconds),
            max(0, settings.default_ai_total_tokens),
            now,
            now,
        ),
    )


def asr_used_seconds_total(db: sqlite3.Connection, user_id: int) -> float:
    row = db.execute(
        """
        SELECT COALESCE(SUM(audio_seconds), 0) AS used
        FROM asr_usage
        WHERE user_id = ?
        """,
        (user_id,),
    ).fetchone()
    return float(row["used"] if row is not None else 0)


def ai_used_tokens_total(db: sqlite3.Connection, user_id: int) -> int:
    row = db.execute(
        """
        SELECT COALESCE(SUM(total_tokens), 0) AS used
        FROM ai_usage
        WHERE user_id = ?
        """,
        (user_id,),
    ).fetchone()
    return int(row["used"] if row is not None else 0)


def check_asr_quota(db: sqlite3.Connection, user_id: int, audio_seconds: float) -> None:
    """Refuse an ASR call before anything is sent upstream, based on known
    audio length. Raises the appropriate API error when disabled or over cap."""
    quota = get_quota(db, user_id)
    if not quota["asr_enabled"]:
        raise_api_error(403, CODE_ASR_DISABLED, "语音识别已被关闭")
    limit = float(quota["asr_total_seconds"] or 0)
    if limit > 0:
        used = asr_used_seconds_total(db, user_id)
        if used + audio_seconds > limit:
            raise_api_error(429, CODE_ASR_QUOTA_EXCEEDED, "语音识别总额度已用完")


def check_ai_quota(db: sqlite3.Connection, user_id: int) -> None:
    """Refuse an AI call when the total token cap is already reached (soft)."""
    quota = get_quota(db, user_id)
    if not quota["ai_enabled"]:
        raise_api_error(403, CODE_AI_DISABLED, "AI 功能已被关闭")
    limit = int(quota["ai_total_tokens"] or 0)
    if limit > 0:
        used = ai_used_tokens_total(db, user_id)
        if used >= limit:
            raise_api_error(429, CODE_AI_QUOTA_EXCEEDED, "AI 总额度已用完")


def record_asr_usage(
    db: sqlite3.Connection,
    user_id: int,
    *,
    request_id: str,
    logid: str | None,
    audio_seconds: float,
    status: str,
    error_code: str | None,
    duration_ms: int,
) -> None:
    db.execute(
        """
        INSERT INTO asr_usage
            (user_id, request_id, logid, audio_seconds, status, error_code,
             duration_ms, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            request_id,
            logid,
            audio_seconds,
            status,
            error_code,
            duration_ms,
            utcish_now_iso(),
        ),
    )
    db.commit()


def record_ai_usage(
    db: sqlite3.Connection,
    user_id: int,
    *,
    purpose: str,
    status: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    cache_hit_tokens: int,
    cache_miss_tokens: int,
    error_code: str | None,
    duration_ms: int,
) -> None:
    db.execute(
        """
        INSERT INTO ai_usage
            (user_id, purpose, status, prompt_tokens, completion_tokens,
             total_tokens, cache_hit_tokens, cache_miss_tokens, error_code,
             duration_ms, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            purpose,
            status,
            prompt_tokens,
            completion_tokens,
            total_tokens,
            cache_hit_tokens,
            cache_miss_tokens,
            error_code,
            duration_ms,
            utcish_now_iso(),
        ),
    )
    db.commit()
