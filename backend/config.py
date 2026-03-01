from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Supabase
    supabase_url: str
    supabase_service_role_key: str
    supabase_anon_key: str
    supabase_storage_bucket: str = "snaps"

    # App
    app_name: str = "SnapClaw"
    debug: bool = False
    base_url: str = "http://localhost:8000"

    # Auth
    jwt_secret: str = "change-me-in-production-use-a-long-random-string"
    jwt_expire_days: int = 30

    # Rate limiting
    rate_limit_register: str = "5/hour"
    rate_limit_login: str = "20/minute"
    rate_limit_api: str = "120/minute"

    # Server
    port: int = 8000
    workers: int = 1

    # Snap defaults
    default_snap_ttl_hours: int = 24
    cleanup_interval_minutes: int = 15

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
