from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover - keeps utility scripts usable before uv sync.
    def load_dotenv(*_args, **_kwargs) -> bool:
        return False


BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _csv_env(name: str, default: str) -> tuple[str, ...]:
    raw = os.getenv(name, default)
    return tuple(item.strip().rstrip("/") for item in raw.split(",") if item.strip())


def _cookie_samesite_env(name: str, default: str) -> str:
    value = os.getenv(name, default).strip().lower()
    if value not in {"lax", "strict", "none"}:
        return default
    return value


@dataclass(frozen=True)
class Settings:
    secret_key: str
    database_path: Path
    cors_origins: tuple[str, ...]
    session_cookie_name: str
    session_days: int
    session_cookie_secure: bool
    session_cookie_samesite: str
    timezone: str
    max_audio_seconds: float
    min_audio_seconds: float
    volc_api_key: str
    volc_app_key: str
    volc_access_key: str
    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_model: str

    @property
    def tzinfo(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    database_path = Path(os.getenv("DATABASE_PATH", "./todo_analyzer.db"))
    if not database_path.is_absolute():
        database_path = BASE_DIR / database_path

    return Settings(
        secret_key=os.getenv("SECRET_KEY", "dev-secret-change-me"),
        database_path=database_path,
        cors_origins=_csv_env(
            "CORS_ORIGINS",
            "http://localhost:8000,http://localhost:5173,http://127.0.0.1:5173",
        ),
        session_cookie_name=os.getenv("SESSION_COOKIE_NAME", "todo_session"),
        session_days=int(os.getenv("SESSION_DAYS", "30")),
        session_cookie_secure=_bool_env("SESSION_COOKIE_SECURE", False),
        session_cookie_samesite=_cookie_samesite_env("SESSION_COOKIE_SAMESITE", "lax"),
        timezone=os.getenv("TIMEZONE", "Asia/Shanghai"),
        max_audio_seconds=float(os.getenv("MAX_AUDIO_SECONDS", "30")),
        min_audio_seconds=float(os.getenv("MIN_AUDIO_SECONDS", "0.5")),
        volc_api_key=os.getenv("VOLC_API_KEY", ""),
        volc_app_key=os.getenv("VOLC_APP_KEY", ""),
        volc_access_key=os.getenv("VOLC_ACCESS_KEY", ""),
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
    )
