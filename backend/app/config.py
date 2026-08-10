from functools import lru_cache
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "TTLAB Research Intelligence Platform"
    runtime_profile: Literal["local", "gcp"] = "local"
    database_url: str = "sqlite:///./data/papers.db"
    cloud_sql_instance: str | None = None
    cloud_sql_database: str = "advisor"
    cloud_sql_iam_user: str | None = None
    cloud_sql_ip_type: Literal["public", "private"] = "public"
    database_pool_size: int = Field(default=5, ge=1, le=32)
    database_max_overflow: int = Field(default=2, ge=0, le=32)
    database_pool_recycle_seconds: int = Field(default=1_800, ge=60, le=86_400)
    expected_database_revision: str = "20260810_01"
    admin_review_lock_dir: Path = Path("data/runtime/review_locks")
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    frontend_url: str = "http://127.0.0.1:5173"
    serve_frontend: bool = False
    frontend_dist_dir: Path = Path("frontend_dist")
    ttlab_publications_url: str = "https://lab.tt/index.php/category/pub/"
    ollama_base_url: str = "http://localhost:11434"
    ollama_default_model: str = "qwen3:4b-instruct-2507-q4_K_M"
    # Ollama tags are mutable.  A model is runnable only when an operator pins
    # its exact digest here (model name -> 64-hex digest or sha256:<digest>).
    ollama_allowed_model_digests: dict[str, str] = {}
    ollama_allow_all_local_models: bool = False
    ollama_timeout_seconds: float = 20.0
    ollama_num_ctx: int = 4096
    ollama_keep_alive: str = "10m"
    google_cloud_project: str | None = None
    google_cloud_location: str = "global"
    gemini_default_model: str = "gemini-3.5-flash"
    gemini_allowed_models: list[str] = ["gemini-3.5-flash"]
    gemini_timeout_seconds: float = Field(default=30.0, gt=0, le=180)
    public_provider_selection: bool = True
    storage_backend: Literal["local_fs", "gcs"] = "local_fs"
    gcs_bucket: str | None = None
    gcs_index_prefix: str = "indexes"
    gcs_index_refresh_seconds: int = Field(default=60, ge=5, le=3_600)
    index_root: Path = Path("data/indexes")
    cloud_cache_dir: Path = Path("/tmp/ttlab")
    dense_embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    dense_embedding_revision: str = "826711e54e001c83835913827a843d8dd0a1def9"
    dense_embedding_device: str = "cpu"

    # Security is deliberately fail-closed for mutations by default.  The
    # one-command demo may opt in to an explicitly insecure loopback-only mode;
    # production may not.
    security_mode: Literal["local_demo", "production"] = "local_demo"
    allow_insecure_local_demo: bool = False
    demo_corpus_preview: bool = False
    auth_actors_json: str = "[]"
    trusted_hosts: list[str] = ["localhost", "127.0.0.1", "testserver"]
    public_base_url: str | None = None
    max_request_bytes: int = 1_048_576
    public_generation_requests_per_minute: int = 20
    rate_limit_hash_salt: str | None = None
    public_generation_max_concurrency: int = Field(default=2, ge=1, le=32)
    public_generation_max_queue: int = Field(default=4, ge=0, le=128)
    public_generation_queue_timeout_seconds: float = Field(default=2.0, gt=0, le=60)
    api_worker_count: int = Field(default=1, ge=1, le=128)
    allowed_llm_providers: list[str] = ["offline_extractive", "ollama"]
    default_llm_provider: Literal["offline_extractive", "ollama", "vertex_gemini"] = "offline_extractive"

    # Downloader controls are an operator-maintained allowlist.  Hosts outside
    # this list are never contacted by the PDF downloader.
    allowed_pdf_hosts: list[str] = ["lab.tt", "temp.lab.tt"]
    max_pdf_download_bytes: int = 25 * 1024 * 1024
    max_pdf_pages: int = 1_000
    max_pdf_redirects: int = 4
    service_role: Literal["api", "offline_worker"] = "api"

    # The scheduler runs in a separate project-owned worker process.  The cron
    # expression is intentionally restricted to one daily UTC/local-time run;
    # this keeps the deployment deterministic without adding a scheduler
    # dependency or allowing every API worker to launch ingestion.
    sync_enabled: bool = False
    sync_execution_mode: Literal["disabled", "offline_single_writer"] = "disabled"
    sync_cron: str = "0 2 * * *"
    sync_timezone: str = "America/La_Paz"
    sync_run_on_startup: bool = False
    sync_worker_poll_seconds: int = Field(default=30, ge=5, le=3_600)
    sync_lock_minutes: int = Field(default=720, ge=5, le=1_440)
    sync_max_pages: int = Field(default=3, ge=1, le=100)
    sync_download_pdfs: bool = True
    sync_dense_index_policy: Literal["if_present", "always", "never"] = "if_present"
    sync_allow_dense_model_download: bool = False
    sync_seed_path: Path = Path("data/runtime/ttlab_publications_discovered.json")

    model_config = SettingsConfigDict(env_prefix="TTLAB_", env_file=".env")

    @property
    def project_root(self) -> Path:
        return Path(__file__).resolve().parents[2]

    @property
    def all_local_ollama_models_enabled(self) -> bool:
        return bool(
            self.security_mode == "local_demo"
            and self.allow_insecure_local_demo
            and self.ollama_allow_all_local_models
        )

    @property
    def is_gcp(self) -> bool:
        return self.runtime_profile == "gcp"

    @model_validator(mode="after")
    def validate_runtime_profile(self) -> "Settings":
        if self.gemini_default_model not in self.gemini_allowed_models:
            raise ValueError("TTLAB_GEMINI_DEFAULT_MODEL must be present in TTLAB_GEMINI_ALLOWED_MODELS")
        if self.runtime_profile != "gcp":
            return self
        missing: list[str] = []
        if not self.cloud_sql_instance:
            missing.append("TTLAB_CLOUD_SQL_INSTANCE")
        if not self.cloud_sql_iam_user:
            missing.append("TTLAB_CLOUD_SQL_IAM_USER")
        if not self.google_cloud_project:
            missing.append("TTLAB_GOOGLE_CLOUD_PROJECT")
        if self.storage_backend != "gcs" or not self.gcs_bucket:
            missing.append("TTLAB_STORAGE_BACKEND=gcs and TTLAB_GCS_BUCKET")
        if missing:
            raise ValueError("GCP runtime profile is missing: " + ", ".join(missing))
        if self.security_mode != "production":
            raise ValueError("TTLAB_RUNTIME_PROFILE=gcp requires TTLAB_SECURITY_MODE=production")
        if self.database_url.startswith("sqlite"):
            raise ValueError("TTLAB_RUNTIME_PROFILE=gcp cannot use SQLite")
        if self.service_role == "api" and self.default_llm_provider != "vertex_gemini":
            raise ValueError("The GCP API requires TTLAB_DEFAULT_LLM_PROVIDER=vertex_gemini")
        if self.service_role == "api" and "vertex_gemini" not in {
            value.strip().lower() for value in self.allowed_llm_providers
        }:
            raise ValueError("The GCP API must allow vertex_gemini")
        if self.public_provider_selection:
            raise ValueError("TTLAB_RUNTIME_PROFILE=gcp requires TTLAB_PUBLIC_PROVIDER_SELECTION=false")
        if not self.rate_limit_hash_salt or len(self.rate_limit_hash_salt) < 32:
            raise ValueError("TTLAB_RUNTIME_PROFILE=gcp requires a 32-character TTLAB_RATE_LIMIT_HASH_SALT")
        return self

    @field_validator("sync_cron")
    @classmethod
    def daily_sync_cron_only(cls, value: str) -> str:
        fields = value.split()
        if len(fields) != 5 or fields[2:] != ["*", "*", "*"]:
            raise ValueError("TTLAB_SYNC_CRON must be a daily five-field expression such as '0 2 * * *'")
        try:
            minute, hour = (int(fields[0]), int(fields[1]))
        except ValueError as exc:
            raise ValueError("TTLAB_SYNC_CRON minute and hour must be integers") from exc
        if not 0 <= minute <= 59 or not 0 <= hour <= 23:
            raise ValueError("TTLAB_SYNC_CRON hour or minute is outside its valid range")
        return f"{minute} {hour} * * *"

    @field_validator("sync_timezone")
    @classmethod
    def valid_sync_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("TTLAB_SYNC_TIMEZONE must be an installed IANA timezone") from exc
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
