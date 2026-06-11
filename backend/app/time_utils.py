from __future__ import annotations

from datetime import date, datetime, timedelta

from app.config import get_settings


def now_shanghai() -> datetime:
    return datetime.now(tz=get_settings().tzinfo)


def today_date() -> date:
    return now_shanghai().date()


def tomorrow_date() -> date:
    return today_date() + timedelta(days=1)


def utcish_now_iso() -> str:
    # SQLite stores timestamps as text. Local timezone keeps debugging aligned with product rules.
    return now_shanghai().isoformat(timespec="seconds")
