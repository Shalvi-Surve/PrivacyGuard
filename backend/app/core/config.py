from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DEVELOPMENT_JWT_SECRET = "development-only-change-this-secret-before-use"


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = "sqlite:///./adaptive_dp.db"
    jwt_secret_key: str = DEVELOPMENT_JWT_SECRET
    jwt_access_token_minutes: int = 30
    cors_allowed_origins: str = ""

    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parents[3] / ".env", extra="ignore")

    @model_validator(mode="after")
    def require_configured_secret_outside_development(self):
        if self.app_env.lower() != "development":
            secret = self.jwt_secret_key.strip()
            lowered = secret.lower()
            if len(secret) < 32 or any(marker in lowered for marker in ("development-only", "replace-with", "change-me", "changeme")):
                raise ValueError("JWT_SECRET_KEY must be a unique secret of at least 32 characters outside development.")
            if self.database_url.strip().lower().startswith("sqlite"):
                raise ValueError("DATABASE_URL must use an explicitly configured server database outside development.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
