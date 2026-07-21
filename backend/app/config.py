from functools import lru_cache
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "TTLAB Research Intelligence Platform"
    database_url: str = "sqlite:///./data/papers.db"
    admin_review_lock_dir: Path = Path("data/runtime/review_locks")
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    frontend_url: str = "http://127.0.0.1:5173"
    ttlab_publications_url: str = "https://lab.tt/index.php/category/pub/"
    ollama_base_url: str = "http://localhost:11434"
    ollama_default_model: str = "qwen3:4b-instruct-2507-q4_K_M"
    # Ollama tags are mutable.  A model is runnable only when an operator pins
    # its exact digest here (model name -> 64-hex digest or sha256:<digest>).
    ollama_allowed_model_digests: dict[str, str] = {}
    ollama_timeout_seconds: float = 20.0
    ollama_num_ctx: int = 4096
    ollama_keep_alive: str = "10m"
    dense_embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    dense_embedding_revision: str = "826711e54e001c83835913827a843d8dd0a1def9"
    dense_embedding_device: str = "cpu"

    # Security is deliberately fail-closed for mutations by default.  The
    # one-command demo may opt in to an explicitly insecure loopback-only mode;
    # production may not.
    security_mode: Literal["local_demo", "production"] = "local_demo"
    allow_insecure_local_demo: bool = False
    auth_actors_json: str = "[]"
    trusted_hosts: list[str] = ["localhost", "127.0.0.1", "testserver"]
    public_base_url: str | None = None
    max_request_bytes: int = 1_048_576
    public_generation_requests_per_minute: int = 20
    api_worker_count: int = Field(default=1, ge=1, le=128)
    allowed_llm_providers: list[str] = ["offline_extractive", "ollama"]
    default_llm_provider: Literal["offline_extractive", "ollama"] = "offline_extractive"

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
