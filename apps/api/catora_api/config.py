from __future__ import annotations

import base64
from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _https_origin(value: str) -> bool:
    parsed = urlsplit(value)
    return (
        parsed.scheme == "https"
        and bool(parsed.netloc)
        and parsed.username is None
        and parsed.password is None
        and parsed.path in ("", "/")
        and not parsed.query
        and not parsed.fragment
    )


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
    enrichment_provider: Literal["disabled", "mock", "http_json"] = "disabled"
    enrichment_max_run_budget_microunits: int = Field(default=100_000, ge=1)
    enrichment_concurrency_limit: int = Field(default=4, ge=1, le=32)
    enrichment_max_attempts: int = Field(default=2, ge=1, le=5)
    enrichment_max_output_tokens: int = Field(default=2_000, ge=1, le=32_000)
    enrichment_http_endpoint: str | None = None
    enrichment_http_api_key: str = Field(default="", repr=False)
    enrichment_http_model: str = "catalog-enrichment-v1"
    enrichment_http_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    enrichment_http_max_request_cost_microunits: int = Field(default=100_000, ge=0)

    shopify_enabled: bool = False
    shopify_client_id: str = ""
    shopify_client_secret: str = Field(default="", repr=False)
    shopify_callback_url: str = "http://localhost:8000/api/v1/shopify/oauth/callback"
    shopify_required_scopes: list[str] = ["read_products"]
    shopify_expiring_offline_tokens: bool = True
    shopify_oauth_state_ttl_minutes: int = Field(default=10, ge=5, le=30)
    shopify_credential_encryption_key: str = Field(default="", repr=False)
    shopify_http_timeout_seconds: float = Field(default=30.0, gt=0, le=120)

    def shopify_encryption_key_bytes(self) -> bytes:
        try:
            key = base64.urlsafe_b64decode(
                self.shopify_credential_encryption_key.encode("ascii")
            )
        except (ValueError, UnicodeEncodeError) as exc:
            raise ValueError(
                "CATORA_SHOPIFY_CREDENTIAL_ENCRYPTION_KEY must be URL-safe base64"
            ) from exc
        if len(key) != 32:
            raise ValueError(
                "CATORA_SHOPIFY_CREDENTIAL_ENCRYPTION_KEY must decode to 32 bytes"
            )
        return key

    def validate_shopify(self) -> None:
        if not self.shopify_enabled:
            return
        if len(self.shopify_client_id.strip()) < 8:
            raise ValueError("CATORA_SHOPIFY_CLIENT_ID is required")
        if len(self.shopify_client_secret) < 16:
            raise ValueError("CATORA_SHOPIFY_CLIENT_SECRET is required")

        callback = urlsplit(self.shopify_callback_url)
        if self.environment == "production":
            if callback.scheme != "https" or not callback.netloc:
                raise ValueError("CATORA_SHOPIFY_CALLBACK_URL must use HTTPS in production")
        elif not self.shopify_callback_url.startswith(("http://localhost:", "https://")):
            raise ValueError("CATORA_SHOPIFY_CALLBACK_URL must use HTTPS outside localhost")
        if (
            callback.path != "/api/v1/shopify/oauth/callback"
            or callback.query
            or callback.fragment
        ):
            raise ValueError("CATORA_SHOPIFY_CALLBACK_URL must use the canonical callback path")

        scopes = [scope.strip() for scope in self.shopify_required_scopes if scope.strip()]
        if scopes != ["read_products"]:
            raise ValueError("Catora's pilot Shopify app must request only read_products")
        if self.environment == "production" and not self.shopify_expiring_offline_tokens:
            raise ValueError("Production Shopify installations must use expiring offline tokens")
        self.shopify_encryption_key_bytes()

    def validate_production(self) -> None:
        if self.environment != "production":
            self.validate_shopify()
            return
        insecure = {"change-me-in-production", "test", "catora", ""}
        if self.s3_secret_key in insecure:
            raise ValueError("CATORA_S3_SECRET_KEY must be a production secret")
        if self.auth_token_pepper in insecure or len(self.auth_token_pepper) < 32:
            raise ValueError("CATORA_AUTH_TOKEN_PEPPER must be a production secret")
        if not self.database_url.startswith("postgresql+"):
            raise ValueError("Production database must use PostgreSQL")
        if not _https_origin(self.frontend_url):
            raise ValueError("CATORA_FRONTEND_URL must be an HTTPS origin in production")
        if not self.cors_origins or any(not _https_origin(origin) for origin in self.cors_origins):
            raise ValueError("CATORA_CORS_ORIGINS must contain only HTTPS origins in production")
        normalized_frontend = self.frontend_url.rstrip("/")
        normalized_origins = {origin.rstrip("/") for origin in self.cors_origins}
        if normalized_frontend not in normalized_origins:
            raise ValueError("CATORA_CORS_ORIGINS must include CATORA_FRONTEND_URL")
        if not self.trust_proxy_headers:
            raise ValueError("CATORA_TRUST_PROXY_HEADERS must be true in production")
        if self.enrichment_provider == "mock":
            raise ValueError(
                "The deterministic mock enrichment provider is not allowed in production"
            )
        if self.enrichment_provider == "http_json":
            endpoint = self.enrichment_http_endpoint or ""
            if not endpoint.startswith("https://"):
                raise ValueError(
                    "CATORA_ENRICHMENT_HTTP_ENDPOINT must use HTTPS in production"
                )
            if len(self.enrichment_http_api_key) < 16:
                raise ValueError(
                    "CATORA_ENRICHMENT_HTTP_API_KEY must be a production secret"
                )
            if not self.enrichment_http_model.strip():
                raise ValueError("CATORA_ENRICHMENT_HTTP_MODEL is required")
        self.validate_shopify()


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.validate_production()
    return settings
