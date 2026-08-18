"""Application settings loaded from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Central application configuration."""

    model_config = SettingsConfigDict(env_prefix="VIDEO_", env_file=".env")

    redis_url: str = "redis://localhost:6379/0"
    upload_dir: Path = PROJECT_ROOT / "data" / "uploads"
    output_dir: Path = PROJECT_ROOT / "data" / "outputs"

    max_file_size: int = 4 * 1024 * 1024 * 1024  # 4GB
    allowed_extensions: set[str] = {
        ".mp4",
        ".mkv",
        ".mov",
        ".avi",
        ".webm",
        ".flv",
        ".ts",
        ".m4v",
    }

    worker_concurrency: int = 1
    job_ttl_hours: int = 24

    # Enable hw accel codec selection in UI
    hardware_accel: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()