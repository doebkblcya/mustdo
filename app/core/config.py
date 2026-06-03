from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./todo_analyzer.db"

    ai_provider: Literal["mock", "openai_compatible"] = "mock"
    ai_base_url: str = "https://api.openai.com/v1"
    ai_api_key: str | None = None
    ai_model_cheap: str | None = None
    ai_model_balanced: str | None = None
    ai_model_strong: str | None = None
    ai_request_timeout_seconds: float = 30.0
    ai_max_output_tokens: int = 1200
    ai_temperature: float = 0.1
    ai_response_format: Literal["json_schema", "json_object", "none"] = "json_schema"
    ai_prompt_cache_key: str | None = Field(default=None)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
