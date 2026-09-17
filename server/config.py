from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="LOOPCODE_", extra="ignore")

    database_url: str = "sqlite:///./data/loopcode.db"
    runner_url: str = "http://runner:8001"
    runner_timeout_seconds: float = Field(default=600, ge=1, le=1200)
    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")
    openai_generation_model: str = Field(default="gpt-5-mini", validation_alias="OPENAI_GENERATION_MODEL")
    openai_tutor_model: str = Field(default="gpt-5-mini", validation_alias="OPENAI_TUTOR_MODEL")
    run_jobs_inline: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
