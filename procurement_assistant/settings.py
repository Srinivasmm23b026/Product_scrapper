from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import quote_plus

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", populate_by_name=True)

    app_env: str = "development"
    database_url: str = (
        "postgresql+psycopg://procurement:procurement@localhost:5432/procurement"
    )
    auth_provider: Literal["supabase", "cognito"] = "supabase"
    supabase_url: str | None = None
    supabase_anon_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SUPABASE_PUBLISHABLE_KEY", "SUPABASE_ANON_KEY"),
    )
    supabase_service_role_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY"),
    )
    supabase_jwt_audience: str = "authenticated"
    auth_redirect_url: str | None = None
    provider_timeout_seconds: int = 15
    aws_region: str = "ap-south-1"
    cognito_user_pool_id: str | None = None
    cognito_app_client_id: str | None = None
    cookie_secure: bool = False
    offer_stale_after_hours: int = 48
    db_host: str | None = None
    db_port: int = 5432
    db_name: str = "procurement"
    db_user: str | None = None
    db_password: str | None = None
    db_pool_size: int = 5
    db_max_overflow: int = 2
    db_use_null_pool: bool = False
    object_storage_provider: Literal["local", "supabase", "s3"] = "local"
    object_storage_bucket: str = "raw-scrapes"
    local_storage_path: Path = Path("/tmp/procurement-raw")
    raw_snapshot_bucket: str | None = None
    raw_snapshot_prefix: str = "raw-scrapes"
    metrics_provider: Literal["logs", "cloudwatch"] = "logs"
    cloudwatch_namespace: str | None = None

    @property
    def resolved_database_url(self) -> str:
        if self.db_host and self.db_user and self.db_password is not None:
            user = quote_plus(self.db_user)
            password = quote_plus(self.db_password)
            return (
                f"postgresql+psycopg://{user}:{password}@{self.db_host}:"
                f"{self.db_port}/{self.db_name}"
            )
        return self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
