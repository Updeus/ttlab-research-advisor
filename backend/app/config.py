from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "TTLAB Research Intelligence Platform"
    database_url: str = "sqlite:///./data/papers.db"
    cors_origins: list[str] = ["http://localhost:5173"]
    ttlab_publications_url: str = "https://lab.tt/index.php/category/pub/"

    model_config = SettingsConfigDict(env_prefix="TTLAB_", env_file=".env")

    @property
    def project_root(self) -> Path:
        return Path(__file__).resolve().parents[2]


@lru_cache
def get_settings() -> Settings:
    return Settings()
