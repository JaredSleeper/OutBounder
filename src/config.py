from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str
    log_level: str = "INFO"
    public_url: str = ""

    # Shared password for the hosted draft; empty disables auth.
    app_password: str = ""

    anthropic_api_key: str = ""
    default_llm_model: str = "claude-sonnet-5"
    exa_api_key: str = ""
    firecrawl_api_key: str = ""
    hunter_api_key: str = ""

    smtp_verify_enabled: bool = True
    smtp_timeout_seconds: float = 8.0

    worker_enabled: bool = True
    worker_concurrency: int = 3
    worker_poll_seconds: float = 2.0

    @property
    def auth_enabled(self) -> bool:
        return bool(self.app_password)

    @property
    def llm_configured(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def exa_configured(self) -> bool:
        return bool(self.exa_api_key)


settings = Settings()
