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


@dataclass(frozen=True)
class Settings:
    secret_key: str
    database_path: Path
    frontend_origin: str
    session_cookie_name: str
    session_days: int
    session_cookie_secure: bool
    timezone: str
    max_audio_seconds: float
    min_audio_seconds: float
    iflytek_app_id: str
    iflytek_api_key: str
    iflytek_api_secret: str
    iflytek_iat_host: str
    iflytek_iat_path: str
    iflytek_language: str
    iflytek_accent: str
    iflytek_connect_timeout_seconds: float
    iflytek_final_timeout_seconds: float
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
        frontend_origin=os.getenv("FRONTEND_ORIGIN", "http://localhost:8000"),
        session_cookie_name=os.getenv("SESSION_COOKIE_NAME", "todo_session"),
        session_days=int(os.getenv("SESSION_DAYS", "30")),
        session_cookie_secure=_bool_env("SESSION_COOKIE_SECURE", False),
        timezone=os.getenv("TIMEZONE", "Asia/Shanghai"),
        max_audio_seconds=float(os.getenv("MAX_AUDIO_SECONDS", "30")),
        min_audio_seconds=float(os.getenv("MIN_AUDIO_SECONDS", "0.5")),
        iflytek_app_id=os.getenv("IFLYTEK_APP_ID", ""),
        iflytek_api_key=os.getenv("IFLYTEK_API_KEY", ""),
        iflytek_api_secret=os.getenv("IFLYTEK_API_SECRET", ""),
        iflytek_iat_host=os.getenv("IFLYTEK_IAT_HOST", "iat-api.xfyun.cn"),
        iflytek_iat_path=os.getenv("IFLYTEK_IAT_PATH", "/v2/iat"),
        iflytek_language=os.getenv("IFLYTEK_LANGUAGE", "zh_cn"),
        iflytek_accent=os.getenv("IFLYTEK_ACCENT", "mandarin"),
        iflytek_connect_timeout_seconds=float(os.getenv("IFLYTEK_CONNECT_TIMEOUT_SECONDS", "10")),
        iflytek_final_timeout_seconds=float(os.getenv("IFLYTEK_FINAL_TIMEOUT_SECONDS", "10")),
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
    )
