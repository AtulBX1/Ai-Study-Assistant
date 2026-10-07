"""Environment-backed application configuration."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    backend: Literal["local", "prod"] = "local"
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    backend_log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    database_url: str = "sqlite:///./data/study_assistant.db"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret_key: str = "local-development-key-change-before-deploying"
    jwt_algorithm: Literal["HS256"] = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    rate_limit_ip_per_minute: int = 120
    rate_limit_user_per_minute: int = 60
    qdrant_url: str | None = None
    qdrant_api_key: str | None = None
    qdrant_local_path: str = str(PROJECT_ROOT / "data" / "qdrant")
    qdrant_collection: str = "document_chunks"
    storage_path: str = "../storage"
    hf_home: str = str(PROJECT_ROOT / "models" / "hf")
    embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    reranker_model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    embedding_device: str = "cpu"
    embedding_batch_size: int = Field(default=16, ge=1, le=256)
    hybrid_dense_weight: float = Field(default=0.5, ge=0, le=1)
    rrf_k: int = Field(default=60, ge=1)
    max_pdf_size_bytes: int = Field(default=20 * 1024 * 1024, gt=0)
    max_pdf_pages: int = Field(default=500, gt=0)
    page_image_cache_size: int = Field(default=32, gt=0)
    s3_endpoint_url: str | None = None
    s3_region: str = "us-east-1"
    s3_bucket: str = "study-documents"
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    minio_bucket: str = "study-documents"

    @property
    def cors_origin_list(self) -> list[str]:
        """Return configured CORS origins as a normalized list."""
        return [
            origin.strip() for origin in self.cors_origins.split(",") if origin.strip()
        ]

    def validate_database_backend(self) -> None:
        """Prevent production configuration from silently using a local database."""
        if self.backend == "prod" and self.database_url.startswith("sqlite"):
            raise ValueError("BACKEND=prod requires a non-SQLite DATABASE_URL.")

    def validate_auth_settings(self) -> None:
        """Reject unsafe production signing keys and invalid token lifetimes."""
        if self.backend == "prod" and (
            len(self.jwt_secret_key) < 32
            or self.jwt_secret_key == "local-development-key-change-before-deploying"
        ):
            raise ValueError(
                "JWT_SECRET_KEY must be a non-default secret of at least 32 characters."
            )
        if self.access_token_minutes <= 0 or self.refresh_token_days <= 0:
            raise ValueError("JWT token lifetimes must be positive.")

    def validate_vector_backend(self) -> None:
        """Require a Qdrant server URL for production vector search."""
        if self.backend == "prod" and not self.qdrant_url:
            raise ValueError("QDRANT_URL is required when BACKEND=prod.")

    def validate_file_storage_backend(self) -> None:
        """Require an S3 bucket for production file storage."""
        if self.backend == "prod" and not self.s3_bucket:
            raise ValueError("S3_BUCKET is required when BACKEND=prod.")


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
