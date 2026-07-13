from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "TTLAB Research Intelligence Platform"
    database_url: str = "sqlite:///./data/papers.db"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    frontend_url: str = "http://127.0.0.1:5173"
    ttlab_publications_url: str = "https://lab.tt/index.php/category/pub/"
    ollama_base_url: str = "http://localhost:11434"
    ollama_default_model: str = "qwen3:4b-instruct-2507-q4_K_M"
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
    allowed_llm_providers: list[str] = ["offline_extractive", "ollama"]

    # Downloader controls are an operator-maintained allowlist.  Hosts outside
    # this list are never contacted by the PDF downloader.
    allowed_pdf_hosts: list[str] = ["lab.tt", "temp.lab.tt"]
    max_pdf_download_bytes: int = 25 * 1024 * 1024
    max_pdf_pages: int = 1_000
    max_pdf_redirects: int = 4

    model_config = SettingsConfigDict(env_prefix="TTLAB_", env_file=".env")

    @property
    def project_root(self) -> Path:
        return Path(__file__).resolve().parents[2]


@lru_cache
def get_settings() -> Settings:
    return Settings()
