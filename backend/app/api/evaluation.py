from typing import Annotated

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.db import get_session
from app.evaluation.dashboard import build_evaluation_dashboard
from app.api.public import redact_local_paths

router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])


@router.get("/dashboard")
def evaluation_dashboard(session: Annotated[Session, Depends(get_session)]) -> dict[str, object]:
    return redact_local_paths(build_evaluation_dashboard(session))
