from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    # App
    app_name: str = "Observatory"
    environment: str = "development"
    debug: bool = True
    api_v1_prefix: str = "/api/v1"

    # Database
    database_url: str = "postgresql+asyncpg://observatory:observatory_dev@localhost:5432/observatory"
    database_echo: bool = False

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # S3 / MinIO
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "observatory"
    s3_secret_key: str = "observatory_dev"
    s3_bucket: str = "observatory"

    # Auth
    jwt_secret: str = "dev-secret-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expiration_minutes: int = 60 * 24  # 24 hours

    # Anthropic
    anthropic_api_key: str = ""
    llm_default_model: str = "claude-sonnet-4-20250514"
    llm_synthesis_model: str = "claude-opus-4-20250514"
    llm_classification_model: str = "claude-haiku-4-5-20251001"

    # LLM Budgets
    llm_daily_token_budget: int = 1_000_000
    llm_cache_ttl_seconds: int = 86400  # 24 hours

    # Celery
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"


@lru_cache
def get_settings() -> Settings:
    return Settings()
