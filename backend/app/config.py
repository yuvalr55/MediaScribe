"""Application configuration.

Every tunable in the system is declared here and sourced from the environment
(or an `.env` file). Nothing elsewhere in the codebase should read `os.environ`
directly — depend on `get_settings()` instead. This keeps configuration
discoverable, typed, and validated in a single place.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed application settings, loaded from the environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    # --- Service ---------------------------------------------------------
    app_name: str = "MediaScribe"
    environment: str = Field(default="development")
    log_level: str = Field(default="INFO")
    log_json: bool = Field(default=True)

    # --- HTTP / CORS -----------------------------------------------------
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_auth_token: str | None = None
    cors_allow_origins: list[str] = Field(default_factory=lambda: ["*"])

    # --- MongoDB ---------------------------------------------------------
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_database: str = "mediascribe"

    # --- RabbitMQ / Celery ----------------------------------------------
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672//"
    celery_task_queue: str = "transcription"
    celery_concurrency: int = 2
    celery_max_retries: int = 3
    celery_retry_backoff_base_seconds: int = 2
    stuck_job_timeout_seconds: int = 600
    stuck_job_reaper_interval_seconds: int = 60

    # --- Storage ---------------------------------------------------------
    storage_backend: str = Field(default="local")  # local | (s3 in future)
    storage_local_path: str = "/data/uploads"

    # --- Upload limits ---------------------------------------------------
    max_upload_bytes: int = 2 * 1024 * 1024 * 1024  # 2 GiB
    upload_chunk_bytes: int = 1024 * 1024  # 1 MiB streaming reads
    allowed_content_types: list[str] = Field(
        default_factory=lambda: [
            "audio/mpeg",
            "audio/wav",
            "audio/x-wav",
            "audio/mp4",
            "audio/m4a",
            "audio/x-m4a",
            "audio/webm",
            "audio/ogg",
            "video/mp4",
            "video/quicktime",
            "video/webm",
        ]
    )

    # --- Transcription model --------------------------------------------
    transcriber: str = Field(default="whisper")  # whisper | fake (tests)
    whisper_model: str = "openai/whisper-base"
    whisper_device: str = "cpu"  # cpu | cuda
    whisper_language: str | None = None  # None => auto-detect

    # --- Audio chunking --------------------------------------------------
    # Files longer than `chunk_threshold_seconds` are split and processed in
    # parallel; shorter files are transcribed in a single task.
    chunk_threshold_seconds: float = 60.0
    chunk_length_seconds: float = 30.0
    chunk_overlap_seconds: float = 1.0
    audio_sample_rate: int = 16_000  # Whisper requires 16 kHz mono


    # --- Observability ---------------------------------------------------
    metrics_enabled: bool = True

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    """Return a cached settings instance (parsed once per process)."""
    return Settings()
