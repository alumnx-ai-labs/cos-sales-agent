from functools import lru_cache

from dotenv import load_dotenv
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# pydantic-settings resolves a field by checking each configured SOURCE in priority
# order (OS environment, then the .env file, then field defaults), and WITHIN a source,
# tries AliasChoices in order -- it does NOT let a lower-priority source's alias beat a
# higher-priority source's alias. So if this machine has a system-wide OS environment
# variable named plain MONGODB_DATABASE (set by some other, unrelated application), that
# would always win over SALES_AGENT_MONGODB_DATABASE declared only in this project's .env
# file, even though AliasChoices lists the project-specific name first. Explicitly
# loading .env into the OS environment (without clobbering anything already set there)
# ensures SALES_AGENT_MONGODB_* is present in that same top-priority source, so its
# alias-order preference actually takes effect. override=False is essential: it must
# never clobber a real OS-level value (from this shell, or a test's monkeypatch) --
# only fill in names that aren't set anywhere else yet.
load_dotenv(".env", override=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"

    # SALES_AGENT_MONGODB_* takes priority over the generic MONGODB_* names. This machine
    # also runs another, unrelated system that sets MONGODB_URI/MONGODB_DATABASE as
    # system-wide OS environment variables (which always outrank this project's own .env
    # file) -- without the project-specific alias, this project would silently read that
    # other system's database. The generic names remain as a fallback for anyone who
    # hasn't hit that collision.
    mongodb_uri: str = Field(
        default="mongodb://localhost:27017",
        validation_alias=AliasChoices("SALES_AGENT_MONGODB_URI", "MONGODB_URI"),
    )
    mongodb_database: str = Field(
        default="cos_sales",
        validation_alias=AliasChoices("SALES_AGENT_MONGODB_DATABASE", "MONGODB_DATABASE"),
    )

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
