from functools import lru_cache
from pathlib import Path
from pydantic import Field, HttpUrl
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application configuration loaded from environment variables or defaults."""

    app_name: str = Field(default="SupplyHub")
    debug: bool = Field(default=False)
    database_url: str = Field(
        default="postgresql+asyncpg://supplyhub:supplyhub@localhost:5432/supplyhub",
        description="SQLAlchemy async database URL",
    )
    redis_url: str = Field(default="redis://localhost:6379/0")
    celery_broker_url: str = Field(default="redis://localhost:6379/1")
    celery_result_backend: str = Field(default="redis://localhost:6379/2")
    base_dir: Path = Field(default=Path("/srv/supplyhub"))
    blocked_doc_patterns_path: Path = Field(
        default=Path(__file__).resolve().parents[1] / "blocklist.txt",
        description="Path to regex patterns that drop documents from processing.",
    )
    blocked_doc_patterns_case_sensitive: bool = Field(
        default=False,
        description="Treat blocklist regex patterns as case-sensitive.",
    )
    ocr_endpoint: HttpUrl | None = Field(
        default=None,
        description="External OCR endpoint. Leave unset to use built-in dots.ocr runtime.",
    )
    json_filler_endpoint: HttpUrl = Field(default="http://json-filler.internal/v1/fill")
    low_conf_threshold: float = Field(default=0.75)
    report_timezone: str = Field(default="UTC")
    preview_max_width: int = Field(default=1280)
    preview_max_height: int = Field(default=960)
    status_cache_ttl: int = Field(default=10, description="Seconds to cache system load snapshot")
    use_stub_services: bool = Field(
        default=False,
        description="Use built-in stubs for OCR/JSON filler instead of external services.",
    )
    telegram_bot_token: str | None = Field(
        default=None,
        description="Telegram bot token for feedback forwarding.",
    )
    telegram_chat_id: str | None = Field(
        default=None,
        description="Telegram chat ID to receive feedback messages.",
    )

    class Config:
        env_prefix = "SUPPLYHUB_"
        case_sensitive = False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings instance."""

    return Settings()
