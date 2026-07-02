from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, func, select

from app.db import get_session
from app.models import Paper

router = APIRouter(prefix="/api", tags=["papers"])


@router.get("/papers", response_model=list[Paper])
def list_papers(session: Annotated[Session, Depends(get_session)]) -> list[Paper]:
    return list(session.exec(select(Paper).order_by(Paper.year.desc(), Paper.title)).all())


@router.get("/papers/{paper_id}", response_model=Paper)
def get_paper(paper_id: str, session: Annotated[Session, Depends(get_session)]) -> Paper:
    paper = session.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    return paper


@router.get("/stats")
def get_stats(session: Annotated[Session, Depends(get_session)]) -> dict[str, object]:
    papers = list(session.exec(select(Paper)).all())
    total = session.exec(select(func.count()).select_from(Paper)).one()
    with_pdf = sum(1 for paper in papers if paper.pdf_url)
    missing_pdf = sum(1 for paper in papers if paper.pdf_text_status == "missing_pdf")
    topics: dict[str, int] = {}
    for paper in papers:
        for topic in paper.topics:
            topics[topic] = topics.get(topic, 0) + 1
    recent = sorted(papers, key=lambda item: (item.year or 0, item.created_at), reverse=True)[:5]
    return {
        "papers": total,
        "with_pdf_url": with_pdf,
        "missing_pdf": missing_pdf,
        "top_topics": sorted(topics.items(), key=lambda item: item[1], reverse=True)[:10],
        "recent_papers": recent,
        "evaluation_status": "not_started",
    }
