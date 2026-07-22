from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Session, select

from app.models.admin import FeatureSetting

FEATURE_DEFINITIONS: dict[str, dict[str, str]] = {
    "papers": {"label": "Paper catalogue", "description": "Browse paper metadata and source text."},
    "search": {"label": "Search", "description": "Keyword, hybrid, and semantic retrieval."},
    "ask": {"label": "Ask TTLAB", "description": "Citation-grounded questions over approved papers."},
    "finder": {"label": "Thesis Extension Finder", "description": "Rank papers and propose grounded extensions."},
    "explorer": {"label": "Topic and author explorer", "description": "Explore reviewed topic, author, and paper links."},
    "artifacts": {"label": "Summaries and podcast scripts", "description": "View and generate paper intelligence artifacts."},
    "evaluation": {"label": "Evaluation dashboard", "description": "View retrieval and grounding evaluation evidence."},
    "ollama": {"label": "Local Ollama generation", "description": "Allow approved local models for generation."},
}


def ensure_feature_settings(session: Session) -> list[FeatureSetting]:
    existing = {item.feature_key: item for item in session.exec(select(FeatureSetting)).all()}
    changed = False
    for key in FEATURE_DEFINITIONS:
        if key not in existing:
            item = FeatureSetting(feature_key=key, enabled=True)
            session.add(item)
            existing[key] = item
            changed = True
    if changed:
        session.commit()
    return [existing[key] for key in FEATURE_DEFINITIONS]


def feature_payload(session: Session) -> dict[str, object]:
    settings = ensure_feature_settings(session)
    return {
        "features": [
            {
                "key": item.feature_key,
                **FEATURE_DEFINITIONS[item.feature_key],
                "enabled": item.enabled,
                "disabled_message": item.disabled_message,
                "updated_at": item.updated_at,
            }
            for item in settings
        ]
    }


def set_feature(session: Session, key: str, enabled: bool, actor_id: str, message: str | None = None) -> FeatureSetting:
    if key not in FEATURE_DEFINITIONS:
        raise KeyError(key)
    item = session.get(FeatureSetting, key) or FeatureSetting(feature_key=key)
    item.enabled = enabled
    item.disabled_message = message.strip()[:500] if message and message.strip() else None
    item.updated_by = actor_id
    item.updated_at = datetime.now(UTC)
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def feature_for_path(path: str) -> str | None:
    if not path.startswith("/api/") or path.startswith(("/api/admin", "/api/auth", "/api/features")):
        return None
    if "/artifacts" in path:
        return "artifacts"
    if path.startswith("/api/papers") or path == "/api/stats":
        return "papers"
    if path.startswith(("/api/search", "/api/index-health")):
        return "search"
    if path.startswith("/api/ask"):
        return "ask"
    if path.startswith("/api/recommendations"):
        return "finder"
    if path.startswith(("/api/explorer", "/api/topics", "/api/authors")):
        return "explorer"
    if path.startswith("/api/evaluation"):
        return "evaluation"
    if path.startswith("/api/llms"):
        return "ollama"
    return None
