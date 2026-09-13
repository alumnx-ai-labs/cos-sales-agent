from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"

    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_database: str = "cos_sales"

    email_limit: int = 50

    email_provider: str = "demo"
    calendar_provider: str = "mock"
    llm_provider: str = "mock"

    llm_api_key: str = ""
    llm_model: str = ""

    mcp_email_enabled: bool = False
    mcp_calendar_enabled: bool = False

    simulation_mode: bool = True

    timezone: str = "Asia/Kolkata"

    log_level: str = "INFO"

    demo_seed: int = 42


@lru_cache
def get_settings() -> Settings:
    return Settings()
