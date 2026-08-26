from functools import lru_cache
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    app_env: str = "development"
    database_url: str = (
        "postgresql+psycopg://procurement:procurement@localhost:5432/procurement"
    )
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
    raw_snapshot_bucket: str | None = None
    raw_snapshot_prefix: str = "raw-scrapes"
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
