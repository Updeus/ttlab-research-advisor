from __future__ import annotations

from sqlmodel import Session, select
from sqlalchemy.exc import OperationalError

from app.config import Settings, get_settings
from app.db import engine
from app.models.admin import FeatureSetting, OllamaModelPolicy


def seed_ollama_policy_from_environment(session: Session, settings: Settings | None = None) -> int:
    settings = settings or get_settings()
    if session.exec(select(OllamaModelPolicy)).first() is not None:
        return 0
    pins = {
        name: digest.removeprefix("sha256:").lower()
        for name, digest in settings.ollama_allowed_model_digests.items()
    }
    for name, digest in pins.items():
        session.add(
            OllamaModelPolicy(
                model_name=name,
                digest=digest,
                enabled=True,
                is_default=name == settings.ollama_default_model,
                updated_by="environment-bootstrap",
            )
        )
    if pins:
        session.commit()
    return len(pins)


def effective_ollama_policy(settings: Settings | None = None) -> tuple[dict[str, str], str, str]:
    settings = settings or get_settings()
    fallback = {
        name: digest.removeprefix("sha256:").lower()
        for name, digest in settings.ollama_allowed_model_digests.items()
    }
    try:
        with Session(engine) as session:
            feature = session.get(FeatureSetting, "ollama")
            rows = list(session.exec(select(OllamaModelPolicy)).all())
    except OperationalError as exc:
        if "no such table" not in str(exc).lower():
            raise
        feature = None
        rows = []
    if feature is not None and not feature.enabled:
        return {}, settings.ollama_default_model, "database_feature_disabled"
    if not rows:
        return fallback, settings.ollama_default_model, "environment"
    enabled = {row.model_name: row.digest.lower() for row in rows if row.enabled}
    configured_default = next((row.model_name for row in rows if row.enabled and row.is_default), None)
    default_model = configured_default or next(iter(enabled), settings.ollama_default_model)
    return enabled, default_model, "database"
