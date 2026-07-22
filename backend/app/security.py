from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import re
from dataclasses import dataclass
from typing import Annotated, Literal
from urllib.parse import urlparse

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.config import Settings, get_settings

Role = Literal["reviewer", "admin"]
ReviewerType = Literal["human", "ai", "service"]

_ACTOR_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$")
_SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")


class TokenActorRecord(BaseModel):
    """A non-secret actor record configured through the environment.

    Only a SHA-256 digest is stored.  The bearer token itself must be generated
    out of band and must never be committed or logged.
    """

    model_config = ConfigDict(extra="forbid")

    token_sha256: str
    actor_id: str
    display_name: str = Field(min_length=1, max_length=120)
    role: Role
    reviewer_type: ReviewerType
    active: bool = True

    @field_validator("token_sha256")
    @classmethod
    def validate_digest(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _SHA256_RE.fullmatch(normalized):
            raise ValueError("token_sha256 must be a 64-character hexadecimal SHA-256 digest")
        return normalized

    @field_validator("actor_id")
    @classmethod
    def validate_actor_id(cls, value: str) -> str:
        normalized = value.strip()
        if not _ACTOR_ID_RE.fullmatch(normalized):
            raise ValueError("actor_id contains unsupported characters or is too long")
        return normalized


@dataclass(frozen=True)
class AuthenticatedActor:
    actor_id: str
    display_name: str
    role: Role
    reviewer_type: ReviewerType
    request_id: str
    local_demo_bypass: bool = False


bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="ReviewerAdminBearer",
    description=(
        "Environment-configured bearer token for reviewer/admin operations. "
        "The server stores only SHA-256 token digests."
    ),
)


def parse_actor_records(settings: Settings) -> list[TokenActorRecord]:
    try:
        payload = json.loads(settings.auth_actors_json or "[]")
    except json.JSONDecodeError as exc:
        raise ValueError("TTLAB_AUTH_ACTORS_JSON must contain valid JSON") from exc
    if not isinstance(payload, list):
        raise ValueError("TTLAB_AUTH_ACTORS_JSON must be a JSON array")
    try:
        records = [TokenActorRecord.model_validate(item) for item in payload]
    except ValidationError as exc:
        raise ValueError(f"Invalid actor record in TTLAB_AUTH_ACTORS_JSON: {exc}") from exc
    digests = [record.token_sha256 for record in records]
    actor_ids = [record.actor_id for record in records]
    if len(digests) != len(set(digests)):
        raise ValueError("TTLAB_AUTH_ACTORS_JSON contains duplicate token digests")
    if len(actor_ids) != len(set(actor_ids)):
        raise ValueError("TTLAB_AUTH_ACTORS_JSON contains duplicate actor IDs")
    return records


def validate_security_configuration(settings: Settings) -> None:
    records = parse_actor_records(settings)
    if settings.max_request_bytes < 16_384:
        raise ValueError("TTLAB_MAX_REQUEST_BYTES must be at least 16384")
    if settings.public_generation_requests_per_minute < 1:
        raise ValueError("TTLAB_PUBLIC_GENERATION_REQUESTS_PER_MINUTE must be positive")
    if settings.max_pdf_download_bytes < 1_048_576:
        raise ValueError("TTLAB_MAX_PDF_DOWNLOAD_BYTES must be at least 1048576")
    if settings.max_pdf_pages < 1 or settings.max_pdf_redirects < 0:
        raise ValueError("PDF page and redirect limits must be non-negative and usable")
    if not settings.allowed_pdf_hosts:
        raise ValueError("TTLAB_ALLOWED_PDF_HOSTS must contain at least one explicit host")
    supported_providers = {"offline_extractive", "ollama"}
    if not settings.allowed_llm_providers or not set(settings.allowed_llm_providers).issubset(supported_providers):
        raise ValueError("TTLAB_ALLOWED_LLM_PROVIDERS contains an unsupported provider")
    if settings.default_llm_provider not in settings.allowed_llm_providers:
        raise ValueError("TTLAB_DEFAULT_LLM_PROVIDER must be present in TTLAB_ALLOWED_LLM_PROVIDERS")
    for model_name, digest in settings.ollama_allowed_model_digests.items():
        normalized = digest.removeprefix("sha256:").lower()
        if not model_name.strip() or not _SHA256_RE.fullmatch(normalized):
            raise ValueError("TTLAB_OLLAMA_ALLOWED_MODEL_DIGESTS must map model names to immutable SHA-256 digests")
    if not settings.trusted_hosts or any("*" in host for host in settings.trusted_hosts):
        raise ValueError("TTLAB_TRUSTED_HOSTS must contain explicit hosts and may not use wildcards")
    if any(origin == "*" for origin in settings.cors_origins):
        raise ValueError("Wildcard CORS origins are not permitted")
    for origin in settings.cors_origins:
        parsed = urlparse(origin)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(f"Invalid exact CORS origin: {origin}")
    if settings.security_mode == "production":
        if settings.allow_insecure_local_demo:
            raise ValueError("Production cannot enable insecure local-demo authentication bypass")
        if not records or not any(record.active and record.role == "admin" for record in records):
            raise ValueError("Production requires at least one active environment-configured admin actor")
        if not settings.public_base_url or not settings.public_base_url.startswith("https://"):
            raise ValueError("Production requires an https TTLAB_PUBLIC_BASE_URL")
        public_hostname = urlparse(settings.public_base_url).hostname
        if public_hostname not in settings.trusted_hosts:
            raise ValueError("Production public hostname must be present in TTLAB_TRUSTED_HOSTS")
        if any(urlparse(origin).scheme != "https" for origin in settings.cors_origins):
            raise ValueError("Production CORS origins must use https")
        if settings.service_role != "api" or settings.sync_execution_mode != "disabled":
            raise ValueError("Production API mode cannot run PDF acquisition, parsing, or ingestion workers")
        if settings.api_worker_count != 1:
            raise ValueError(
                "The built-in public generation limiter is process-local; production requires one API worker "
                "unless an external distributed limiter is implemented"
            )


def require_offline_pdf_worker(settings: Settings, operation: str) -> None:
    """Fail closed unless a local, explicitly isolated worker owns PDF work."""

    allowed = (
        settings.security_mode != "production"
        and settings.service_role == "offline_worker"
        and settings.sync_execution_mode == "offline_single_writer"
    )
    if not allowed:
        raise RuntimeError(
            f"{operation} is disabled in production/API mode; run it only in an explicit offline worker. "
            "Production requires externally enforced network egress and process isolation."
        )


def operational_boundary_diagnostics(settings: Settings) -> dict[str, object]:
    """Report application guarantees and deliberately unimplemented controls."""

    pdf_enabled = (
        settings.security_mode != "production"
        and settings.service_role == "offline_worker"
        and settings.sync_execution_mode == "offline_single_writer"
    )
    rate_topology_supported = settings.api_worker_count == 1
    return {
        "pdf_processing": {
            "application_mode": settings.service_role,
            "live_acquisition_and_parsing_enabled": pdf_enabled,
            "production_api_enabled": False,
            "required_external_controls": [
                "network-egress-isolated worker",
                "process isolation and resource limits",
                "DNS pinning or egress proxy resistant to rebinding TOCTOU",
            ],
            "external_controls_implemented_by_application": False,
            "dns_rebinding_toctou_fully_mitigated": False,
        },
        "rate_limiting": {
            "implementation": "process_local_memory",
            "configured_api_workers": settings.api_worker_count,
            "supported_topology": "single_api_worker",
            "topology_supported": rate_topology_supported,
            "distributed_limiter_implemented": False,
            "external_distributed_limiter_required_for_multiple_workers": True,
        },
        "generation_capacity": {
            "implementation": "process_local_bounded_queue",
            "max_active_requests": settings.public_generation_max_concurrency,
            "max_waiting_requests": settings.public_generation_max_queue,
            "queue_timeout_seconds": settings.public_generation_queue_timeout_seconds,
            "covered_paths": ["POST /api/ask", "POST /api/recommendations/extensions"],
            "distributed_admission_control_implemented": False,
        },
    }


def _unauthorized(detail: str = "Authentication required") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_actor(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthenticatedActor:
    request_id = str(getattr(request.state, "request_id", "unavailable"))
    if credentials is None:
        if (
            settings.security_mode == "local_demo"
            and settings.allow_insecure_local_demo
            and request_is_loopback(request)
        ):
            return record_actor(
                request,
                AuthenticatedActor(
                    actor_id="local-demo-bypass",
                    display_name="Insecure local demo",
                    role="admin",
                    reviewer_type="service",
                    request_id=request_id,
                    local_demo_bypass=True,
                ),
            )
        raise _unauthorized()
    if credentials.scheme.lower() != "bearer":
        raise _unauthorized("Unsupported authentication scheme")
    raw_token = credentials.credentials
    # Thirty-two characters is a conservative lower bound; deployment guidance
    # requires a randomly generated 256-bit value (normally longer when encoded).
    if len(raw_token) < 32:
        raise _unauthorized("Invalid bearer token")
    presented_digest = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    for record in parse_actor_records(settings):
        if record.active and hmac.compare_digest(presented_digest, record.token_sha256):
            return record_actor(
                request,
                AuthenticatedActor(
                    actor_id=record.actor_id,
                    display_name=record.display_name,
                    role=record.role,
                    reviewer_type=record.reviewer_type,
                    request_id=request_id,
                ),
            )
    raise _unauthorized("Invalid bearer token")


def request_is_loopback(request: Request) -> bool:
    if request.client is None:
        return False
    hostname = request.client.host.strip().lower()
    if hostname == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def record_actor(request: Request, actor: AuthenticatedActor) -> AuthenticatedActor:
    request.state.actor_id = actor.actor_id
    request.state.actor_role = actor.role
    return actor


def get_optional_actor(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthenticatedActor | None:
    if credentials is None:
        if (
            settings.security_mode == "local_demo"
            and settings.allow_insecure_local_demo
            and request_is_loopback(request)
        ):
            return get_current_actor(request, credentials, settings)
        return None
    return get_current_actor(request, credentials, settings)


def require_reviewer(
    actor: Annotated[AuthenticatedActor, Depends(get_current_actor)],
) -> AuthenticatedActor:
    if actor.role not in {"reviewer", "admin"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Reviewer role required")
    return actor


def require_admin(
    actor: Annotated[AuthenticatedActor, Depends(get_current_actor)],
) -> AuthenticatedActor:
    if actor.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return actor
