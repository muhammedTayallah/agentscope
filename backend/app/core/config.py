from functools import lru_cache

from pydantic import SecretStr, field_validator
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

    # Production: directory of the built UI to serve at / (the API then moves to /api),
    # and whether to run the ARQ worker inside the web process.
    static_dir: str = ""
    run_worker: bool = False

    @field_validator("database_url", "test_database_url")
    @classmethod
    def _asyncpg_scheme(cls, url: str) -> str:
        """Hosts (e.g. Render) hand out postgres:// or postgresql:// URLs; the async engine
        needs the asyncpg driver in the scheme."""
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+asyncpg://" + url[len(prefix) :]
        return url

    # Integration tests run against these when set (they wipe the data).
    test_database_url: str = ""
    test_redis_url: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
