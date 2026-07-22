"""Fail-closed publication and content-access policy.

Technical corpus eligibility answers whether extracted text is usable.  It is
not an editorial publication decision and it is not evidence that TTLAB may
redistribute source text.  Public routes therefore require the independent
states in this module before a paper can be displayed or ranked.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from sqlmodel import Session, select

from app.indexing.chunker import canonical_chunks_sha256, db_chunk_payload
from app.config import Settings
from app.models import Chunk, Paper

PublicationStatus = Literal["pending_review", "published", "hidden"]
RightsStatus = Literal["unknown", "cleared", "restricted"]
PublicAccessLevel = Literal["hidden", "metadata_only", "searchable"]

PUBLICATION_STATUSES = {"pending_review", "published", "hidden"}
RIGHTS_STATUSES = {"unknown", "cleared", "restricted"}
PUBLIC_ACCESS_LEVELS = {"hidden", "metadata_only", "searchable"}


def local_demo_corpus_preview_enabled(settings: Settings) -> bool:
    """Allow unreviewed corpus inspection only in the explicit insecure local demo."""

    return bool(
        settings.security_mode == "local_demo"
        and settings.allow_insecure_local_demo
        and settings.demo_corpus_preview
    )


def is_local_demo_content(session: Session, paper: Paper) -> bool:
    """Require a technically eligible, generation-bound record for demo retrieval."""

    return bool(
        paper.corpus_eligibility_status == "eligible"
        and has_current_content_generation(paper, require_public_index=False)
        and content_generation_diagnostics(session, paper)["ready"]
    )


def has_current_content_generation(paper: Paper, *, require_public_index: bool = True) -> bool:
    """Check persisted links without trusting legacy or partially promoted rows."""

    generation = str(paper.extraction_generation_id or "")
    chunk_generation = str(paper.chunk_generation_id or "")
    linked = bool(
        re.fullmatch(r"[0-9a-f]{64}", generation)
        and re.fullmatch(r"[0-9a-f]{64}", chunk_generation)
        and paper.chunk_extraction_generation_id == generation
        and paper.chunk_count > 0
    )
    if not linked:
        return False
    return not require_public_index or paper.public_index_generation_id == chunk_generation


def content_generation_diagnostics(session: Session, paper: Paper) -> dict[str, Any]:
    """Verify that the database chunk mirror belongs to the current extraction."""

    blockers: list[str] = []
    if not has_current_content_generation(paper, require_public_index=False):
        blockers.append("generation_link_missing")
    chunks = list(
        session.exec(
            select(Chunk)
            .where(Chunk.paper_id == paper.paper_id)
            .order_by(Chunk.chunk_index, Chunk.chunk_id)
        ).all()
    )
    if len(chunks) != paper.chunk_count or not chunks:
        blockers.append("chunk_count_mismatch")
    if any(chunk.extraction_generation_id != paper.extraction_generation_id for chunk in chunks):
        blockers.append("chunk_extraction_generation_mismatch")
    # Reuse the chunk artifact contract rather than maintaining a second hash
    # implementation for publication. This binds public delivery to the exact
    # canonical database bytes that were reviewed and promoted.
    observed_hash = canonical_chunks_sha256(db_chunk_payload(chunks))
    if chunks and observed_hash != paper.chunk_generation_id:
        blockers.append("chunk_generation_hash_mismatch")
    return {
        "ready": not blockers,
        "blockers": list(dict.fromkeys(blockers)),
        "extraction_generation_id": paper.extraction_generation_id,
        "chunk_generation_id": paper.chunk_generation_id,
        "observed_chunk_generation_id": observed_hash if chunks else None,
        "chunk_count": len(chunks),
    }


def is_public_metadata(paper: Paper) -> bool:
    """Return whether reviewed metadata may be shown on public surfaces."""

    return bool(
        paper.review_status == "approved"
        and paper.publication_status == "published"
        and paper.rights_status == "cleared"
        and paper.public_access_level in {"metadata_only", "searchable"}
    )


def is_public_content(session: Session, paper: Paper) -> bool:
    """Return whether source-derived text may be searched and cited publicly.

    Persisted generation identifiers are necessary but not sufficient. The
    observed canonical chunk payload must still hash to the promoted generation
    identifier, so direct or accidental database edits fail closed on every
    public delivery path until the normal rebuild and review workflow runs.
    """

    return bool(
        is_public_metadata(paper)
        and paper.public_access_level == "searchable"
        and paper.corpus_eligibility_status == "eligible"
        and paper.extraction_review_status == "approved"
        and has_current_content_generation(paper)
        and content_generation_diagnostics(session, paper)["ready"]
    )


def public_papers(session: Session, *, content_required: bool = False) -> list[Paper]:
    """Load the explicitly published set; unknown legacy rows remain hidden."""

    statement = (
        select(Paper)
        .where(Paper.review_status == "approved")
        .where(Paper.publication_status == "published")
        .where(Paper.rights_status == "cleared")
    )
    if content_required:
        statement = (
            statement.where(Paper.public_access_level == "searchable")
            .where(Paper.corpus_eligibility_status == "eligible")
            .where(Paper.extraction_review_status == "approved")
            .where(Paper.extraction_generation_id.is_not(None))
            .where(Paper.chunk_generation_id.is_not(None))
            .where(Paper.chunk_extraction_generation_id == Paper.extraction_generation_id)
            .where(Paper.public_index_generation_id == Paper.chunk_generation_id)
            .where(Paper.chunk_count > 0)
        )
    else:
        statement = statement.where(Paper.public_access_level.in_(["metadata_only", "searchable"]))
    papers = list(session.exec(statement.order_by(Paper.title, Paper.paper_id)).all())
    if content_required:
        papers = [paper for paper in papers if content_generation_diagnostics(session, paper)["ready"]]
    return papers


def publication_state(session: Session, paper: Paper) -> dict[str, str | bool]:
    return {
        "publication_status": paper.publication_status,
        "rights_status": paper.rights_status,
        "public_access_level": paper.public_access_level,
        "public_metadata_visible": is_public_metadata(paper),
        "public_content_searchable": is_public_content(session, paper),
    }
