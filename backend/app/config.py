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


@dataclass(frozen=True)
class Settings:
    secret_key: str
    database_path: Path
    session_days: int
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
        session_days=int(os.getenv("SESSION_DAYS", "30")),
        timezone=os.getenv("TIMEZONE", "Asia/Shanghai"),
        max_audio_seconds=float(os.getenv("MAX_AUDIO_SECONDS", "60")),
        min_audio_seconds=float(os.getenv("MIN_AUDIO_SECONDS", "0.5")),
        volc_api_key=os.getenv("VOLC_API_KEY", ""),
        volc_app_key=os.getenv("VOLC_APP_KEY", ""),
        volc_access_key=os.getenv("VOLC_ACCESS_KEY", ""),
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
    )
