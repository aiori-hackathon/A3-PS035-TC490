from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    PROJECT_NAME: str = Field(default="NEXORA", description="Project Name")
    SERVICE_NAME: str = Field(default="nexora-backend", description="Backend Service Identifier")
    VERSION: str = Field(default="0.1.0", description="API Version")
    ENVIRONMENT: str = Field(default="development", description="Runtime environment")
    DEBUG: bool = Field(default=False, description="Debug mode")

    HOST: str = Field(default="0.0.0.0", description="Backend host binding")
    PORT: int = Field(default=8000, description="Backend port binding")

    API_V1_PREFIX: str = Field(default="/api/v1", description="Prefix for API v1 routes")

    # CORS configuration - explicitly configured origins
    CORS_ALLOWED_ORIGINS: list[str] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000"],
        description="List of allowed CORS origins",
    )

    DATABASE_URL: str = Field(
        default="sqlite:///./nexora.db",
        description="Database connection string",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
