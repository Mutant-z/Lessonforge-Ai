from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "LessonForge AI"
    environment: str = "development"
    secret_key: str = "development-only-change-this-secret-key"
    access_token_expire_minutes: int = 480
    database_url: str = "sqlite+aiosqlite:///../storage/app.db"
    storage_root: Path = Path("../storage")
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:8080"]
    max_upload_mb: int = 30
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4.1-mini"
    llm_provider: str = "mock"
    llm_timeout_seconds: int = 180
    llm_max_tokens: int = 16000
    default_language: str = "zh-CN"
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, value):
        return value.split(",") if isinstance(value, str) else value

    def prepare_storage(self) -> None:
        for name in ("uploads", "generated", "temp"):
            (self.storage_root / name).mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()

