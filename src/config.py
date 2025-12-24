"""Application configuration using pydantic-settings.

All configuration is loaded from environment variables with sensible defaults.
Secrets should NEVER be logged or exposed in error messages.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    All settings are immutable after initialization.
    Secrets are wrapped in SecretStr to prevent accidental exposure.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/kk_exec",
        description="Async database connection URL",
    )
    database_url_sync: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/kk_exec",
        description="Sync database connection URL (for Alembic)",
    )
    database_pool_size: int = Field(default=5, ge=1, le=100)
    database_max_overflow: int = Field(default=10, ge=0, le=100)
    database_pool_timeout: int = Field(default=30, ge=1, le=300)

    # Encryption
    encryption_key: SecretStr = Field(
        ...,
        description="Fernet key for credential encryption",
    )

    # LLM Configuration
    openai_api_key: SecretStr = Field(
        ...,
        description="OpenAI API key",
    )
    default_model: str = Field(
        default="gpt-4o",
        description="Default LLM model for workflow generation",
    )
    llm_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    llm_max_tokens: int = Field(default=4096, ge=1, le=128000)
    llm_timeout: int = Field(default=60, ge=1, le=600)

    # MCP Configuration
    mcp_timeout: int = Field(
        default=30,
        ge=1,
        le=300,
        description="Timeout for MCP server connections in seconds",
    )
    mcp_max_retries: int = Field(default=3, ge=0, le=10)
    mcp_retry_delay: float = Field(default=1.0, ge=0.1, le=60.0)

    # Redis
    redis_url: str = Field(
        default="redis://localhost:6379",
        description="Redis connection URL for ARQ background tasks",
    )

    # Server Configuration
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000, ge=1, le=65535)
    debug: bool = Field(default=False)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO"
    )

    # JWT Authentication
    jwt_secret_key: SecretStr = Field(
        ...,
        description="Secret key for JWT token signing",
    )
    jwt_algorithm: str = Field(default="HS256")
    jwt_access_token_expire_minutes: int = Field(default=30, ge=1, le=10080)

    # CORS
    cors_origins: str = Field(
        default="http://localhost:3000",
        description="Comma-separated list of allowed origins",
    )

    # Execution
    execution_timeout: int = Field(
        default=300,
        ge=1,
        le=3600,
        description="Maximum workflow execution time in seconds",
    )
    execution_max_steps: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="Maximum number of steps per workflow execution",
    )

    # OAuth Providers - Slack
    slack_client_id: str | None = Field(
        default=None,
        description="Slack OAuth app client ID",
    )
    slack_client_secret: SecretStr | None = Field(
        default=None,
        description="Slack OAuth app client secret",
    )
    slack_redirect_uri: str = Field(
        default="https://hiklik.ai/api/v1/oauth/slack/callback",
        description="Slack OAuth redirect URI",
    )

    # OAuth Providers - GitHub
    github_client_id: str | None = Field(
        default=None,
        description="GitHub OAuth app client ID",
    )
    github_client_secret: SecretStr | None = Field(
        default=None,
        description="GitHub OAuth app client secret",
    )
    github_redirect_uri: str = Field(
        default="https://hiklik.ai/api/v1/oauth/github/callback",
        description="GitHub OAuth redirect URI",
    )

    # OAuth Providers - Notion
    notion_client_id: str | None = Field(
        default=None,
        description="Notion OAuth integration client ID",
    )
    notion_client_secret: SecretStr | None = Field(
        default=None,
        description="Notion OAuth integration client secret",
    )
    notion_redirect_uri: str = Field(
        default="https://hiklik.ai/api/v1/oauth/notion/callback",
        description="Notion OAuth redirect URI",
    )

    # Frontend URL (for OAuth callback redirects)
    frontend_url: str = Field(
        default="https://hiklik.ai",
        description="Frontend URL for OAuth callback redirects",
    )

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(cls, v: str) -> str:
        """Validate CORS origins format."""
        origins = [o.strip() for o in v.split(",") if o.strip()]
        if not origins:
            raise ValueError("At least one CORS origin must be specified")
        return v

    @property
    def cors_origins_list(self) -> list[str]:
        """Get CORS origins as a list."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def get_masked_key(self, key_name: str) -> str:
        """Get a masked version of a secret key for logging.

        Only shows first 8 characters followed by '...'
        """
        secret = getattr(self, key_name, None)
        if secret is None:
            return "<not set>"
        if isinstance(secret, SecretStr):
            value = secret.get_secret_value()
        else:
            value = str(secret)
        if len(value) <= 8:
            return "***"
        return f"{value[:8]}..."


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance.

    Settings are loaded once and cached for the application lifetime.
    Use dependency injection in FastAPI routes to access settings.
    """
    return Settings()


# Export commonly used settings accessors
settings = get_settings()
