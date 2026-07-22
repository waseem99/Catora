from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CATORA_",
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
    )

    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    database_url: str = "postgresql+asyncpg://catora:catora@localhost:5432/catora"
    redis_url: str = "redis://localhost:6379/0"
    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "catora"
    s3_secret_key: str = Field(default="change-me-in-production", repr=False)
    s3_bucket: str = "catora"
    max_catalog_upload_bytes: int = 25 * 1024 * 1024
    cors_origins: list[str] = ["http://localhost:3000"]
    frontend_url: str = "http://localhost:3000"
    auth_token_pepper: str = Field(default="development-token-pepper-change-me", repr=False)
    session_cookie_name: str = "catora_session"
    csrf_cookie_name: str = "catora_csrf"
    session_ttl_hours: int = 12
    invitation_ttl_hours: int = 72
    password_reset_ttl_minutes: int = 30
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_from: str = "Catora <no-reply@catora.local>"
    trust_proxy_headers: bool = False
    enrichment_provider: Literal["disabled", "mock"] = "disabled"
    enrichment_max_run_budget_microunits: int = Field(default=100_000, ge=1)
    enrichment_concurrency_limit: int = Field(default=4, ge=1, le=32)
    enrichment_max_attempts: int = Field(default=2, ge=1, le=5)
    enrichment_max_output_tokens: int = Field(default=2_000, ge=1, le=32_000)
    enrichment_max_job_retries: int = Field(default=2, ge=0, le=10)

    def validate_production(self) -> None:
        if self.environment != "production":
            return
        insecure = {"change-me-in-production", "test", "catora", ""}
        if self.s3_secret_key in insecure:
            raise ValueError("CATORA_S3_SECRET_KEY must be a production secret")
        if self.auth_token_pepper in insecure or len(self.auth_token_pepper) < 32:
            raise ValueError("CATORA_AUTH_TOKEN_PEPPER must be a production secret")
        if not self.database_url.startswith("postgresql+"):
            raise ValueError("Production database must use PostgreSQL")
        if self.enrichment_provider == "mock":
            raise ValueError(
                "The deterministic mock enrichment provider is not allowed in production"
            )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.validate_production()
    return settings
