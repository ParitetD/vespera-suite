"""Конфигурация через pydantic-settings (.env и переменные окружения)."""

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[1]
APP_DIR = BASE_DIR / "app"
DATA_DIR = BASE_DIR / "data"
STATIC_DIR = APP_DIR / "static"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    # AI Copilot
    openai_api_key: Optional[str] = Field(default=None, alias="OPENAI_API_KEY")
    ai_model: str = Field(default="gpt-4o-mini", alias="AI_MODEL")
    ai_base_url: Optional[str] = Field(default=None, alias="AI_BASE_URL")

    hibp_api_key: Optional[str] = Field(default=None, alias="HIBP_API_KEY")
    serpapi_key: Optional[str] = Field(default=None, alias="SERPAPI_KEY")
    vk_access_token: Optional[str] = Field(default=None, alias="VK_ACCESS_TOKEN")
    numverify_api_key: Optional[str] = Field(default=None, alias="NUMVERIFY_API_KEY")
    proxy_url: Optional[str] = Field(default=None, alias="PROXY_URL")
    rate_limit_default: float = Field(default=1.0, alias="RATE_LIMIT_DEFAULT")
    request_timeout: float = Field(default=30.0, alias="REQUEST_TIMEOUT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    db_path: Path = Field(default=DATA_DIR / "vespera.db", alias="DB_PATH")
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8000, alias="PORT")
    title: str = Field(default="Vespera Search Suite", alias="TITLE")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
