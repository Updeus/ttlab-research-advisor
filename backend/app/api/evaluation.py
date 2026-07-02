from typing import Annotated

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.db import get_session
from app.evaluation.dashboard import build_evaluation_dashboard

router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])


@router.get("/dashboard")
def evaluation_dashboard(session: Annotated[Session, Depends(get_session)]) -> dict[str, object]:
    return build_evaluation_dashboard(session)
