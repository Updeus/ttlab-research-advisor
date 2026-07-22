from typing import Annotated

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.db import get_session
from app.features import feature_payload

router = APIRouter(prefix="/api/features", tags=["features"])


@router.get("")
def public_features(session: Annotated[Session, Depends(get_session)]) -> dict[str, object]:
    return feature_payload(session)
