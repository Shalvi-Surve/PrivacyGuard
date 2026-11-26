import pytest
from pydantic import ValidationError

from app.core.config import DEVELOPMENT_JWT_SECRET, Settings


def test_development_may_use_the_local_only_secret_default(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    settings = Settings(_env_file=None)
    assert settings.app_env == "development"
    assert settings.jwt_secret_key == DEVELOPMENT_JWT_SECRET


@pytest.mark.parametrize(
    "secret",
    [DEVELOPMENT_JWT_SECRET, "short-secret", "replace-with-a-unique-secret-that-is-long-enough"],
)
def test_non_development_rejects_default_short_or_template_jwt_secrets(secret):
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        Settings(app_env="production", jwt_secret_key=secret, _env_file=None)


def test_non_development_accepts_a_configured_secret_of_sufficient_length():
    settings = Settings(app_env="production", database_url="postgresql+psycopg://localhost/privacyguard", jwt_secret_key="locally-supplied-test-secret-with-40-chars", _env_file=None)
    assert settings.app_env == "production"


def test_non_development_rejects_the_local_sqlite_database_default():
    with pytest.raises(ValidationError, match="DATABASE_URL"):
        Settings(app_env="production", jwt_secret_key="locally-supplied-test-secret-with-40-chars", _env_file=None)
