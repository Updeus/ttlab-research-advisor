from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy import text
from sqlmodel import Session

from app.api.admin import router as admin_router
from app.api.artifacts import router as artifacts_router
from app.api.ask import router as ask_router
from app.api.evaluation import router as evaluation_router
from app.api.explorer import router as explorer_router
from app.api.llms import router as llms_router
from app.api.papers import router as papers_router
from app.api.recommendations import router as recommendations_router
from app.api.search import router as search_router
from app.config import get_settings
from app.db import create_db_and_tables, engine, sqlite_integrity_diagnostics
from app.indexing.embedder import (
    DEFAULT_INDEX_PATH,
    DENSE_INDEX_PATH,
    DENSE_PROVIDER,
    FEATURE_HASHING_PROVIDER,
    index_diagnostics,
    validate_present_authoritative_indexes,
)
from app.indexing.keyword_search import diagnostics as keyword_diagnostics
from app.middleware import PublicRateLimitMiddleware, RequestBodyLimitMiddleware, SecurityHeadersMiddleware
from app.security import operational_boundary_diagnostics, validate_security_configuration

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    validate_security_configuration(settings)
    create_db_and_tables()
    with Session(engine) as session:
        validate_present_authoritative_indexes(session)
    yield


app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
    docs_url="/docs" if settings.security_mode == "local_demo" else None,
    redoc_url="/redoc" if settings.security_mode == "local_demo" else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=["X-Request-ID", "X-TTLAB-Security-Mode", "X-TTLAB-Insecure-Demo"],
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
app.add_middleware(
    RequestBodyLimitMiddleware,
    max_bytes=settings.max_request_bytes,
)
app.add_middleware(
    PublicRateLimitMiddleware,
    requests_per_minute=settings.public_generation_requests_per_minute,
)
app.add_middleware(
    SecurityHeadersMiddleware,
    security_mode=settings.security_mode,
    insecure_demo=settings.security_mode == "local_demo" and settings.allow_insecure_local_demo,
)

app.include_router(papers_router)
app.include_router(search_router)
app.include_router(ask_router)
app.include_router(llms_router)
app.include_router(recommendations_router)
app.include_router(artifacts_router)
app.include_router(admin_router)
app.include_router(evaluation_router)
app.include_router(explorer_router)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "service": settings.app_name,
        "status": "ok",
        "security_mode": settings.security_mode,
        "admin_authentication": "insecure_local_demo_bypass"
        if settings.security_mode == "local_demo" and settings.allow_insecure_local_demo
        else "bearer_token_required",
        "frontend": settings.frontend_url,
        "api_docs": "/docs" if settings.security_mode == "local_demo" else "disabled",
        "health": "/health",
        "readiness": "/ready",
    }


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "ttlab-research-intelligence"}


@app.get("/ready")
def readiness(response: Response) -> dict[str, object]:
    checks: dict[str, object] = {
        "database": False,
        "database_integrity": {},
        "operational_boundaries": operational_boundary_diagnostics(settings),
        "keyword_index": {"required": True, "ready": False, "status": "unknown"},
        "feature_hashing_index": {"required": True, "ready": False, "status": "unknown"},
        "dense_index": {"required": False, "ready": False, "status": "unknown"},
    }
    try:
        with Session(engine) as session:
            session.exec(text("SELECT 1"))
            checks["database"] = True
            checks["database_integrity"] = sqlite_integrity_diagnostics()
            index_checks, ready = readiness_index_checks(session)
            checks.update(index_checks)
            if not ready:
                response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
                return {"status": "not_ready", "checks": checks}
    except Exception:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "not_ready", "checks": checks}
    return {"status": "ready", "checks": checks}


def readiness_index_checks(session: Session) -> tuple[dict[str, dict[str, object]], bool]:
    """Return public-safe readiness states without weakening integrity checks."""

    keyword = keyword_diagnostics(session)
    feature = index_diagnostics(session, DEFAULT_INDEX_PATH, FEATURE_HASHING_PROVIDER)
    dense = index_diagnostics(session, DENSE_INDEX_PATH, DENSE_PROVIDER)

    # Retain the authoritative validator as the single strict present-index
    # gate. A present partial, stale, or corrupt optional dense index is not an
    # acceptable degraded state.
    vector_integrity_valid = True
    try:
        validate_present_authoritative_indexes(session)
    except Exception:
        vector_integrity_valid = False

    keyword_ready = (
        keyword.get("status") == "ready"
        and keyword.get("completeness_status") == "complete"
        and int(keyword.get("keyword_indexed_chunks") or 0) == int(keyword.get("eligible_chunks") or 0)
    )
    feature_ready = feature.get("status") == "ready" and feature.get("completeness_status") == "complete"
    dense_status = str(dense.get("status") or "unknown")
    dense_ready = dense_status == "ready" and dense.get("completeness_status") == "complete"
    dense_acceptable = dense_ready or dense_status == "missing"

    checks = {
        "keyword_index": public_index_check(keyword, required=True, ready=keyword_ready),
        "feature_hashing_index": public_index_check(feature, required=True, ready=feature_ready),
        "dense_index": public_index_check(dense, required=False, ready=dense_ready),
    }
    return checks, bool(keyword_ready and feature_ready and dense_acceptable and vector_integrity_valid)


def public_index_check(
    report: dict[str, object],
    *,
    required: bool,
    ready: bool,
) -> dict[str, object]:
    """Expose readiness facts while withholding local paths and error strings."""

    indexed = report.get("keyword_indexed_chunks", report.get("indexed_chunks", 0))
    return {
        "required": required,
        "ready": ready,
        "status": str(report.get("status") or "unknown"),
        "completeness_status": str(report.get("completeness_status") or "missing"),
        "indexed_chunks": int(indexed or 0),
        "eligible_chunks": int(report.get("eligible_chunks") or 0),
    }
