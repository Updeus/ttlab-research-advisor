from __future__ import annotations

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine
from starlette.requests import Request

from app.admin_accounts import (
    authenticate_admin,
    create_admin_session,
    create_admin_user,
    resolve_admin_session,
)
from app.config import Settings
from app.features import ensure_feature_settings, set_feature
from app.security import get_current_actor, get_optional_actor


def build_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


def request_with_cookies(method: str, raw_session: str, raw_csrf: str) -> Request:
    headers = [
        (b"cookie", f"ttlab_admin_session={raw_session}; ttlab_admin_csrf={raw_csrf}".encode()),
        (b"x-csrf-token", raw_csrf.encode()),
    ]
    request = Request(
        {
            "type": "http",
            "method": method,
            "scheme": "https",
            "path": "/api/admin/control/features/ask",
            "raw_path": b"/api/admin/control/features/ask",
            "query_string": b"",
            "headers": headers,
            "client": ("127.0.0.1", 4000),
            "server": ("advisor.example", 443),
        }
    )
    request.state.request_id = "auth-test"
    return request


def test_local_admin_session_csrf_feature_control_and_account_creation() -> None:
    engine = build_engine()
    settings = Settings(
        security_mode="production",
        public_base_url="https://advisor.example",
        trusted_hosts=["advisor.example"],
        cors_origins=["https://advisor.example"],
    )
    with Session(engine) as session:
        user = create_admin_user(
            session,
            username="jarod",
            display_name="Jarod",
            password="correct horse battery staple",
            created_by="test",
            must_change_password=False,
        )
        assert authenticate_admin(session, "jarod", "wrong") is None
        authenticated = authenticate_admin(session, "jarod", "correct horse battery staple")
        assert authenticated is not None
        raw_session, raw_csrf, _record = create_admin_session(
            session,
            authenticated,
            request_ip="127.0.0.1",
            user_agent="pytest",
        )
        assert resolve_admin_session(session, raw_session) is not None

        actor = get_current_actor(
            request_with_cookies("PATCH", raw_session, raw_csrf),
            None,
            settings,
            session,
        )
        assert actor.actor_id == user.user_id
        assert actor.auth_method == "session"
        optional_actor = get_optional_actor(
            request_with_cookies("GET", raw_session, raw_csrf),
            None,
            settings,
            session,
        )
        assert optional_actor is not None
        assert optional_actor.actor_id == user.user_id

        features = ensure_feature_settings(session)
        assert all(item.enabled for item in features)
        changed = set_feature(session, "ask", False, actor.actor_id, "Maintenance")
        assert changed.enabled is False
        assert changed.disabled_message == "Maintenance"

        second = create_admin_user(
            session,
            username="second-admin",
            display_name="Second Admin",
            password="temporary password value",
            created_by=actor.actor_id,
            must_change_password=True,
        )
        assert second.must_change_password is True
