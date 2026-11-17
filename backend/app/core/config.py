from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.pricing import DEFAULT_PRICES


class Settings(BaseSettings):
    # Repo-root .env when run from backend/; real env vars win.
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    database_url: str = "postgresql+asyncpg://agentscope:agentscope@localhost:5432/agentscope"
    redis_url: str = "redis://localhost:6379/0"
    # Guards project and API-key management. Empty = management API disabled (503).
    admin_token: SecretStr = SecretStr("")
    cors_origins: list[str] = ["http://localhost:5180"]
    # Extra/overriding model prices, USD per 1M tokens: {"model": [input, output]}.
    model_prices: dict[str, tuple[float, float]] = {}

    def all_prices(self) -> dict[str, tuple[float, float]]:
        return {**DEFAULT_PRICES, **self.model_prices}

    # LLM-as-judge for eval runs: "gemini" (default) or "anthropic". Empty model = the
    # provider's default. Without the provider's key the judge scorer is skipped.
    judge_provider: str = "gemini"
    judge_model: str = ""
    gemini_api_key: SecretStr = SecretStr("")
    anthropic_api_key: SecretStr = SecretStr("")

    # Integration tests run against these when set (they wipe the data).
    test_database_url: str = ""
    test_redis_url: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
