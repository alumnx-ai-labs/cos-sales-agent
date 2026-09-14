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

    # The authenticated user's own mailbox. Emails sent FROM this address (e.g. the sales
    # rep's own outbound messages in a two-sided thread) must never get a reply draft
    # generated for them -- see app/pipeline.py's run_pipeline. Defaults to Task 14's demo
    # sales rep address so the demo behaves correctly with zero configuration.
    agent_email: str = "ashok@oursalesagent-demo.example"

    mcp_email_enabled: bool = False
    mcp_calendar_enabled: bool = False

    simulation_mode: bool = True

    timezone: str = "Asia/Kolkata"

    log_level: str = "INFO"

    demo_seed: int = 42


@lru_cache
def get_settings() -> Settings:
    return Settings()
