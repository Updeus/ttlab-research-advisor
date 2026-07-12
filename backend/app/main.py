from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
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
from app.db import create_db_and_tables, engine
from app.indexing.embedder import validate_present_authoritative_indexes

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    create_db_and_tables()
    with Session(engine) as session:
        validate_present_authoritative_indexes(session)
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
        "frontend": "http://127.0.0.1:5173",
        "api_docs": "/docs",
        "health": "/health",
    }


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "ttlab-research-intelligence"}
