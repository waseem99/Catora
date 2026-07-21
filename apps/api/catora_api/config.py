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
    cors_origins: list[str] = ["http://localhost:3000"]

    def validate_production(self) -> None:
        if self.environment != "production":
            return
        insecure = {"change-me-in-production", "test", "catora", ""}
        if self.s3_secret_key in insecure:
            raise ValueError("CATORA_S3_SECRET_KEY must be a production secret")
        if not self.database_url.startswith("postgresql+"):
            raise ValueError("Production database must use PostgreSQL")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.validate_production()
    return settings
