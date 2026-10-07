"""Configuration module using pydantic-settings."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment or .env file."""

    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    gemini_api_key: str | None = Field(default=None, alias="GEMINI_API_KEY")

    claude_model: str = Field(
        default="claude-3-7-sonnet-20250219",
        alias="CLAUDE_MODEL",
        description="Configurable Claude model identifier",
    )
    gemini_model: str = Field(
        default="gemini-2.5-flash",
        alias="GEMINI_MODEL",
        description="Configurable Gemini model identifier",
    )

    max_upload_mb: int = Field(
        default=10,
        alias="MAX_UPLOAD_MB",
        description="Maximum file upload size in MB",
    )
    mock_mode: bool = Field(
        default=False,
        alias="MOCK_MODE",
        description="Run in offline mock mode using pre-recorded fixtures",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()
