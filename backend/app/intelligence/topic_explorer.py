from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete
from sqlmodel import Session, func, select

from app.db import create_db_and_tables, engine
from app.indexing.retriever import retrieve
from app.ingestion.metadata_cleaner import active_author_for_name, ensure_author_identity, normalize_author_key
from app.models import Author, AuthorAlias, AuthorTopic, Chunk, Paper, PaperArtifact, PaperTopic, Topic
from app.publication import is_public_content, is_public_metadata, public_papers

REVIEWED_STATUSES = {"reviewed", "approved"}
PUBLIC_APPROVED_STATUSES = {"approved"}
EXPLORER_SOURCE = "deterministic_explorer"

SPECIAL_LABELS = {
    "ai": "AI",
    "iot": "IoT",
    "ml": "Machine Learning",
    "rag": "RAG",
}

SYNONYM_MAP = {
    "retrieval augmented generation": "rag",
    "retrieval-augmented generation": "rag",
    "rag": "rag",
    "artificial intelligence": "ai",
    "ai": "ai",
    "machine learning": "machine learning",
    "ml": "machine learning",
    "internet of things": "iot",
    "iot": "iot",
    "optimisation": "optimization",
    "optimization": "optimization",
}

TOPIC_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("rag", ("retrieval augmented generation", "retrieval-augmented generation", "rag")),
    ("ai", ("artificial intelligence", "generative ai", "intelligent system")),
    ("machine learning", ("machine learning", "deep learning", "neural network", "classification model")),
    ("information retrieval", ("information retrieval", "search engine", "document retrieval", "retrieval system")),
    ("data science", ("data science", "data analysis", "data-driven", "data centric", "data-centric")),
    ("research discovery", ("research discovery", "academic discovery", "publication discovery", "research archive")),
    ("web applications", ("web application", "web app", "web-based", "data dashboard", "frontend")),
    ("open data", ("open data", "open dataset", "data portal", "real-time data portal")),
    ("education", ("education", "educational", "student", "teaching", "school discipline", "university curricula")),
    ("optimization", ("optimization", "optimisation", "linear programming", "integer programming", "optimal allocation")),
    ("iot", ("internet of things", "iot", "wearable device", "edge device", "sensor network")),
    ("agriculture", ("agriculture", "agricultural", "crop", "farming", "plantation")),
    ("climate", ("climate", "weather", "rainfall", "coastal vulnerability", "deforestation")),
    ("telecommunications", ("telecommunication", "telecom", "wireless", "cellular")),
    ("mobile services", ("mobile data", "mobile service", "m-commerce", "esim", "quality of service", " qos ")),
    ("networks", ("communication network", "wireless network", "cellular network", "social network", "network traffic", "routing")),
    ("visualization", ("visualization", "visualisation", "visual analytics", "data dashboard")),
    ("natural language processing", ("natural language", "nlp", "language model", "text mining")),
    ("summarization", ("summarization", "summarisation", "automatic summary", "text summary")),
    ("chatbots", ("chatbot", "conversational", "personalized feedback")),
    ("clustering", ("clustering", "cluster", "document clustering", "topic modelling", "topic modeling")),
    ("word embeddings", ("word embedding", "word embeddings", "gaussian word")),
    ("cybersecurity", ("security", "cybersecurity", "intrusion", "attack")),
    ("fraud detection", ("fraud", "fraud detection")),
    ("privacy", ("privacy", "obfuscation", "trust framework", "reliable crowd")),
    ("transportation", ("transport", "traffic", "vehicle", "mobility")),
    ("dangerous driving", ("dangerous driving", "driving")),
    ("insurance", ("insurance", "premium", "claim", "claims")),
    ("pricing", ("pricing", "price", "premium rate")),
    ("marketing", ("marketing", "customer contact", "targeted")),
    ("recommendation systems", ("recommender system", "recommendation system", "product recommendation", "playlist shuffling")),
    ("e-commerce", ("e-commerce", "commerce", "m-commerce")),
    ("supply chain", ("supply chain", "product delivery", "product deliveries")),
    ("smart grid", ("smart meter", "meter readings")),
    ("body shape detection", ("body shape", "shape detection")),
    ("civil society", ("civil society", "data4good")),
    ("internet resilience", ("internet resilience", "small island")),
    ("simulation", ("simulation", "simulator", "simulated")),
    ("energy", ("energy", "power grid", "electricity")),
]

STOP_TOPICS = {
    "paper",
    "research",
    "study",
    "method",
    "system",
    "analysis",
}


@dataclass
class TopicCandidate:
    normalized_name: str
    name: str
    score: float = 0.0
    evidence: list[dict[str, Any]] = field(default_factory=list)


def utc_now() -> datetime:
    return datetime.now(UTC)


def normalize_topic(raw_topic: str) -> tuple[str, str] | None:
    cleaned = re.sub(r"\s+", " ", str(raw_topic or "").strip())
    if not cleaned:
        return None
    normalized = re.sub(r"[^a-z0-9+# ]+", " ", cleaned.lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    normalized = SYNONYM_MAP.get(normalized, normalized)
    if not normalized or normalized in STOP_TOPICS or len(normalized) < 2:
        return None
    return normalized, display_label(normalized)


def display_label(normalized_name: str) -> str:
    if normalized_name in SPECIAL_LABELS:
        return SPECIAL_LABELS[normalized_name]
    return " ".join(word.upper() if word in {"api"} else word.capitalize() for word in normalized_name.split())


def topic_id_for(normalized_name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", normalized_name.lower()).strip("-")


def rebuild_topic_index(session: Session) -> dict[str, Any]:
    papers = eligible_papers(session)
    try:
        prior_paper_topic_reviews = snapshot_graph_reviews(session.exec(select(PaperTopic)).all())
        prior_author_topic_reviews = snapshot_graph_reviews(session.exec(select(AuthorTopic)).all())
        session.execute(delete(PaperTopic))
        session.execute(delete(AuthorTopic))

        existing_topics = {topic.normalized_name: topic for topic in session.exec(select(Topic)).all()}
        summary = {
            "topics_created": 0,
            "topics_updated": 0,
            "approved_topics_preserved": 0,
            "paper_topic_links": 0,
            "author_topic_links": 0,
            "preserved_link_reviews": 0,
            "skipped_reviewed_items": 0,
            "warnings": [],
        }

        for paper in papers:
            candidates = topic_candidates_for_paper(session, paper)
            if paper.review_status in REVIEWED_STATUSES and paper.topics:
                summary["skipped_reviewed_items"] += 1
                candidates = candidates_from_reviewed_topics(paper)
            if not candidates:
                summary["warnings"].append(f"No topics inferred for paper_id={paper.paper_id}.")
                continue
            for candidate in sorted(candidates.values(), key=lambda item: item.score, reverse=True)[:8]:
                topic = upsert_topic(session, existing_topics, candidate, summary)
                link = PaperTopic(
                    link_id=f"{paper.paper_id}:{topic.topic_id}",
                    paper_id=paper.paper_id,
                    topic_id=topic.topic_id,
                    score=round(candidate.score, 4),
                    evidence_json=candidate.evidence[:8],
                    source=EXPLORER_SOURCE,
                    created_at=utc_now(),
                )
                if restore_graph_review(link, prior_paper_topic_reviews.get(link.link_id)):
                    summary["preserved_link_reviews"] += 1
                session.add(link)
                summary["paper_topic_links"] += 1
        session.flush()
        update_topic_descriptions(session)
        author_link_count, preserved_author_reviews = rebuild_author_topics(
            session,
            prior_reviews=prior_author_topic_reviews,
        )
        summary["author_topic_links"] = author_link_count
        summary["preserved_link_reviews"] += preserved_author_reviews
        session.commit()
        return summary
    except Exception:
        session.rollback()
        raise


def candidates_from_reviewed_topics(paper: Paper) -> dict[str, TopicCandidate]:
    candidates: dict[str, TopicCandidate] = {}
    for topic in paper.topics:
        add_candidate(
            candidates,
            topic,
            score=3.0,
            source="reviewed_paper_topics",
            text=f"Reviewed paper topic: {topic}",
            field="paper.topics",
        )
    return candidates


def topic_candidates_for_paper(session: Session, paper: Paper) -> dict[str, TopicCandidate]:
    if paper.corpus_eligibility_status != "eligible":
        return {}
    candidates: dict[str, TopicCandidate] = {}
    for topic in paper.topics:
        add_candidate(candidates, topic, score=2.8, source="paper_topics", text=f"Paper topic: {topic}", field="paper.topics")
    for keyword in paper.keywords:
        add_candidate(candidates, keyword, score=1.6, source="paper_keywords", text=f"Paper keyword: {keyword}", field="paper.keywords")

    infer_topics_from_text(candidates, paper.title, score=2.4, source="paper_title", field="title")

    chunks = publication_topic_chunks(session, paper.paper_id)
    for chunk in chunks:
        section = str(chunk.section or "Unknown")
        score = 0.9 if section in {"Abstract", "Introduction"} or chunk.chunk_index == 0 else 0.45
        infer_topics_from_text(
            candidates,
            chunk.text[:1600],
            score=score,
            source="chunk_text",
            field="chunk.text",
            chunk_id=chunk.chunk_id,
        )
    return {
        name: candidate
        for name, candidate in candidates.items()
        if candidate.score >= 1.35 or any(item["source"] in {"paper_topics", "paper_keywords"} for item in candidate.evidence)
    }


def eligible_papers(session: Session, *, public: bool = False) -> list[Paper]:
    """Return the reviewed publication corpus used by the explorer.

    Catalogue-only, unavailable, and source/PDF-mismatch rows remain visible in
    the catalogue but cannot contribute topic or author-expertise evidence.
    """

    if public:
        return [paper for paper in public_papers(session, content_required=True)]
    return list(
        session.exec(
            select(Paper)
            .where(Paper.corpus_eligibility_status == "eligible")
            .order_by(Paper.title, Paper.paper_id)
        ).all()
    )


def publication_topic_chunks(session: Session, paper_id: str) -> list[Chunk]:
    """Select bounded primary-source passages and exclude reference prose.

    Literature-review and reference chunks contain vocabulary about other work
    and produced most of the earlier false-positive topic links.  The title,
    abstract/introduction, methods/results/discussion, and conclusion are the
    defensible publication-derived basis for a paper-level controlled label.
    """

    chunks = list(
        session.exec(
            select(Chunk)
            .where(Chunk.paper_id == paper_id)
            .where(Chunk.section.notin_(["References", "Literature Review"]))
            .order_by(Chunk.chunk_index)
        ).all()
    )
    if not chunks:
        # A small number of legacy PDFs have a section label propagated across
        # the title/abstract chunk.  Retain the first non-reference passage as
        # an explicit bounded fallback instead of dropping the paper entirely.
        chunks = list(
            session.exec(
                select(Chunk)
                .where(Chunk.paper_id == paper_id)
                .where(Chunk.section != "References")
                .order_by(Chunk.chunk_index)
                .limit(2)
            ).all()
        )
    if len(chunks) <= 6:
        return chunks
    first = chunks[:5]
    concluding = next((chunk for chunk in reversed(chunks) if chunk.section in {"Conclusion", "Discussion"}), None)
    if concluding is not None and concluding.chunk_id not in {chunk.chunk_id for chunk in first}:
        first.append(concluding)
    return first


def add_candidate(
    candidates: dict[str, TopicCandidate],
    raw_topic: str,
    *,
    score: float,
    source: str,
    text: str,
    field: str,
    chunk_id: str | None = None,
    artifact_id: str | None = None,
) -> None:
    normalized = normalize_topic(raw_topic)
    if normalized is None:
        return
    normalized_name, name = normalized
    candidate = candidates.setdefault(normalized_name, TopicCandidate(normalized_name=normalized_name, name=name))
    candidate.score += score
    if len(candidate.evidence) < 8:
        candidate.evidence.append(
            {
                "source": source,
                "field": field,
                "text": trim_text(text),
                "chunk_id": chunk_id,
                "artifact_id": artifact_id,
                "score": score,
            }
        )


def infer_topics_from_text(
    candidates: dict[str, TopicCandidate],
    text_value: str | None,
    *,
    score: float,
    source: str,
    field: str,
    chunk_id: str | None = None,
    artifact_id: str | None = None,
) -> None:
    if not text_value:
        return
    searchable = re.sub(r"[^a-z0-9+# ]+", " ", text_value.casefold())
    searchable = re.sub(r"\s+", " ", searchable).strip()
    for normalized_name, terms in TOPIC_RULES:
        if any(phrase_in_text(term, searchable) for term in terms):
            add_candidate(
                candidates,
                normalized_name,
                score=score,
                source=source,
                text=text_value,
                field=field,
                chunk_id=chunk_id,
                artifact_id=artifact_id,
            )


def phrase_in_text(term: str, searchable: str) -> bool:
    normalized_term = re.sub(r"[^a-z0-9+# ]+", " ", term.casefold())
    normalized_term = re.sub(r"\s+", " ", normalized_term).strip()
    if not normalized_term:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(normalized_term)}(?![a-z0-9])", searchable) is not None


def upsert_topic(
    session: Session,
    existing_topics: dict[str, Topic],
    candidate: TopicCandidate,
    summary: dict[str, Any],
) -> Topic:
    topic = existing_topics.get(candidate.normalized_name)
    now = utc_now()
    if topic is None:
        topic = Topic(
            topic_id=topic_id_for(candidate.normalized_name),
            name=candidate.name,
            normalized_name=candidate.normalized_name,
            description=None,
            source=EXPLORER_SOURCE,
            review_status="needs_review",
            created_at=now,
            updated_at=now,
        )
        existing_topics[candidate.normalized_name] = topic
        summary["topics_created"] += 1
    else:
        if topic.review_status == "approved":
            # An approved label may contain a human correction. Rebuilds may
            # refresh evidence links, but must never publish regenerated topic
            # metadata under an earlier human approval.
            summary["approved_topics_preserved"] += 1
        else:
            topic.name = candidate.name
            topic.updated_at = now
            summary["topics_updated"] += 1
    session.add(topic)
    return topic


def update_topic_descriptions(session: Session) -> None:
    session.flush()
    for topic in session.exec(select(Topic)).all():
        if topic.review_status == "approved":
            continue
        paper_count = session.exec(
            select(func.count()).select_from(PaperTopic).where(PaperTopic.topic_id == topic.topic_id)
        ).one()
        topic.description = f"Deterministically linked to {paper_count} indexed TTLAB paper(s)."
        topic.updated_at = utc_now()
        session.add(topic)
    session.flush()


def rebuild_author_topics(
    session: Session,
    *,
    prior_reviews: dict[str, dict[str, Any]] | None = None,
) -> tuple[int, int]:
    papers = eligible_papers(session)
    paper_topics = list(session.exec(select(PaperTopic)).all())
    links_by_paper: dict[str, list[PaperTopic]] = {}
    for link in paper_topics:
        links_by_paper.setdefault(link.paper_id, []).append(link)

    link_count = 0
    preserved_reviews = 0
    for author in session.exec(
        select(Author).where(Author.identity_status.notin_(["merged", "invalid"]))
    ).all():
        author.paper_count = 0
        if author.review_status not in REVIEWED_STATUSES:
            author.research_topics = []
        author.updated_at = utc_now()
        session.add(author)
    canonical_groups: dict[int, tuple[Author, list[Paper]]] = {}
    for author_name, raw_authored_papers in group_papers_by_author(papers).items():
        author = active_author_for_name(session, author_name)
        if author is None:
            author, _created = ensure_author_identity(session, author_name, source="topic_rebuild")
            session.flush()
        if author.id is None:
            continue
        grouped_author, grouped_papers = canonical_groups.setdefault(author.id, (author, []))
        existing_ids = {paper.paper_id for paper in grouped_papers}
        grouped_papers.extend(paper for paper in raw_authored_papers if paper.paper_id not in existing_ids)
        canonical_groups[author.id] = (grouped_author, grouped_papers)

    for author, authored_papers in canonical_groups.values():
        topic_scores: dict[str, dict[str, Any]] = {}
        for paper in authored_papers:
            for link in links_by_paper.get(paper.paper_id, []):
                entry = topic_scores.setdefault(link.topic_id, {"score": 0.0, "papers": set(), "evidence": []})
                entry["score"] += link.score
                entry["papers"].add(paper.paper_id)
                if len(entry["evidence"]) < 6:
                    entry["evidence"].append(
                        {
                            "paper_id": paper.paper_id,
                            "paper_title": paper.title,
                            "score": link.score,
                            "source": "paper_topic_link",
                        }
                    )
        author.paper_count = len(authored_papers)
        if author.review_status not in REVIEWED_STATUSES:
            author.research_topics = [
                display_topic_name(session, topic_id)
                for topic_id, _entry in sorted(topic_scores.items(), key=lambda item: item[1]["score"], reverse=True)[:8]
            ]
        author.updated_at = utc_now()
        session.add(author)
        for topic_id, entry in topic_scores.items():
            if author.id is None:
                continue
            link = AuthorTopic(
                link_id=f"{author.id}:{topic_id}",
                author_id=author.id,
                topic_id=topic_id,
                paper_count=len(entry["papers"]),
                score=round(float(entry["score"]), 4),
                evidence_json=entry["evidence"],
                created_at=utc_now(),
            )
            if restore_graph_review(link, (prior_reviews or {}).get(link.link_id)):
                preserved_reviews += 1
            session.add(link)
            link_count += 1
    return link_count, preserved_reviews


def graph_link_fingerprint(link: PaperTopic | AuthorTopic) -> str:
    if isinstance(link, PaperTopic):
        payload: dict[str, Any] = {
            "kind": "paper_topic",
            "paper_id": link.paper_id,
            "topic_id": link.topic_id,
            "score": round(float(link.score), 8),
            "evidence": link.evidence_json,
            "source": link.source,
        }
    else:
        payload = {
            "kind": "author_topic",
            "author_id": link.author_id,
            "topic_id": link.topic_id,
            "paper_count": link.paper_count,
            "score": round(float(link.score), 8),
            "evidence": link.evidence_json,
        }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def snapshot_graph_reviews(links: list[PaperTopic] | list[AuthorTopic]) -> dict[str, dict[str, Any]]:
    return {
        link.link_id: {
            "fingerprint": graph_link_fingerprint(link),
            "review_status": link.review_status,
            "reviewer_notes": link.reviewer_notes,
            "reviewed_at": link.reviewed_at,
            "reviewed_by": link.reviewed_by,
        }
        for link in links
    }


def restore_graph_review(link: PaperTopic | AuthorTopic, prior: dict[str, Any] | None) -> bool:
    if prior is None or prior.get("fingerprint") != graph_link_fingerprint(link):
        return False
    link.review_status = str(prior.get("review_status") or "needs_review")
    link.reviewer_notes = prior.get("reviewer_notes")
    link.reviewed_at = prior.get("reviewed_at")
    link.reviewed_by = prior.get("reviewed_by")
    return link.review_status != "needs_review"


def group_papers_by_author(papers: list[Paper]) -> dict[str, list[Paper]]:
    grouped: dict[str, list[Paper]] = {}
    for paper in papers:
        for author_name in paper.authors:
            if author_name.strip():
                grouped.setdefault(author_name.strip(), []).append(paper)
    return grouped


def display_topic_name(session: Session, topic_id: str) -> str:
    topic = session.get(Topic, topic_id)
    return topic.name if topic else topic_id.replace("-", " ").title()


def explorer_overview(session: Session) -> dict[str, Any]:
    topics = list(
        session.exec(select(Topic).where(Topic.review_status == "approved").order_by(Topic.name)).all()
    )
    authors = list(
        session.exec(
            select(Author)
            .where(Author.identity_status == "resolved")
            .where(Author.review_status == "approved")
            .where(Author.identity_review_status == "approved")
            .where(Author.paper_count > 0)
            .order_by(Author.name)
        ).all()
    )
    papers = sorted(eligible_papers(session, public=True), key=lambda item: (item.year or 0, item.title), reverse=True)
    public_ids = {paper.paper_id for paper in papers}
    paper_topic_count = (
        session.exec(
            select(func.count())
            .select_from(PaperTopic)
            .where(PaperTopic.paper_id.in_(public_ids))
            .where(PaperTopic.review_status == "approved")
        ).one()
        if public_ids else 0
    )
    public_author_rows = list_authors(session, limit=200)["items"]
    public_author_ids = {row["author_id"] for row in public_author_rows if row.get("author_id") is not None}
    author_topic_count = sum(
        len(top_topics_for_author(session, author))
        for author_id in public_author_ids
        if (author := session.get(Author, author_id)) is not None
    )
    return {
        "topic_count": len(topics),
        "author_count": len(public_author_rows),
        "paper_count": len(papers),
        "linked_paper_topics": paper_topic_count,
        "linked_author_topics": author_topic_count,
        "top_topics": list_topics(session, limit=8)["items"],
        "top_authors": list_authors(session, limit=8)["items"],
        "recent_papers": [paper_summary(paper) for paper in papers[:5]],
        "explorer_index_status": "ready" if paper_topic_count else "empty",
    }


def list_topics(
    session: Session,
    *,
    q: str | None = None,
    min_papers: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    topics = list(
        session.exec(select(Topic).where(Topic.review_status == "approved").order_by(Topic.name)).all()
    )
    rows = [row for topic in topics if (row := topic_card(session, topic))["paper_count"] > 0]
    if q:
        needle = q.lower()
        rows = [row for row in rows if needle in row["name"].lower() or needle in row["normalized_name"]]
    if min_papers is not None:
        rows = [row for row in rows if row["paper_count"] >= min_papers]
    rows.sort(key=lambda item: (item["paper_count"], item["author_count"], item["name"]), reverse=True)
    return {"total": len(rows), "limit": limit, "offset": offset, "items": rows[offset : offset + limit]}


def topic_card(session: Session, topic: Topic) -> dict[str, Any]:
    public_ids = {paper.paper_id for paper in eligible_papers(session, public=True)}
    paper_links = [
        link
        for link in session.exec(
            select(PaperTopic)
            .where(PaperTopic.topic_id == topic.topic_id)
            .where(PaperTopic.review_status == "approved")
        ).all()
        if link.paper_id in public_ids
    ]
    top_authors = public_authors_for_topic(session, paper_links)[:4]
    sample_papers = [
        paper_summary(paper)
        for paper in papers_for_links(session, sorted(paper_links, key=lambda item: item.score, reverse=True)[:4])
    ]
    return {
        "topic_id": topic.topic_id,
        "name": topic.name,
        "normalized_name": topic.normalized_name,
        "description": topic.description,
        "paper_count": len({link.paper_id for link in paper_links}),
        "author_count": len(top_authors),
        "top_authors": top_authors,
        "sample_papers": sample_papers,
        "review_status": topic.review_status,
    }


def topic_detail(session: Session, topic_id: str) -> dict[str, Any] | None:
    topic = session.get(Topic, topic_id) or topic_by_query(session, topic_id)
    if topic is None or topic.review_status != "approved":
        return None
    public_ids = {paper.paper_id for paper in eligible_papers(session, public=True)}
    paper_links = [
        link for link in session.exec(
            select(PaperTopic)
            .where(PaperTopic.topic_id == topic.topic_id)
            .where(PaperTopic.review_status == "approved")
        ).all()
        if link.paper_id in public_ids
    ]
    public_topic_authors = public_authors_for_topic(session, paper_links)
    related = related_topics(session, topic.topic_id, paper_links)
    return {
        **topic_card(session, topic),
        "papers": [
            {
                **paper_summary(paper),
                "score": link.score,
                "evidence": link.evidence_json,
            }
            for link, paper in paper_link_pairs(session, sorted(paper_links, key=lambda item: item.score, reverse=True))
        ],
        "authors": public_topic_authors,
        "related_topics": related,
    }


def topic_by_query(session: Session, value: str) -> Topic | None:
    normalized = normalize_topic(value)
    if normalized is None:
        return None
    return session.exec(select(Topic).where(Topic.normalized_name == normalized[0])).first()


def related_topics(session: Session, topic_id: str, paper_links: list[PaperTopic]) -> list[dict[str, Any]]:
    paper_ids = {link.paper_id for link in paper_links}
    counts: dict[str, int] = {}
    for link in session.exec(
        select(PaperTopic)
        .where(PaperTopic.paper_id.in_(list(paper_ids)))
        .where(PaperTopic.review_status == "approved")
    ).all() if paper_ids else []:
        if link.topic_id == topic_id:
            continue
        counts[link.topic_id] = counts.get(link.topic_id, 0) + 1
    related = []
    for other_topic_id, shared_papers in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:8]:
        topic = session.get(Topic, other_topic_id)
        if topic and topic.review_status == "approved":
            related.append({"topic_id": topic.topic_id, "name": topic.name, "shared_paper_count": shared_papers})
    return related


def list_authors(
    session: Session,
    *,
    q: str | None = None,
    topic: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    authors = list(
        session.exec(
            select(Author)
            .where(Author.identity_status == "resolved")
            .where(Author.review_status == "approved")
            .where(Author.identity_review_status == "approved")
            .where(Author.paper_count > 0)
            .order_by(Author.name)
        ).all()
    )
    if q:
        needle = q.casefold()
        aliases_by_author: dict[int, list[str]] = {}
        for alias in session.exec(select(AuthorAlias).where(AuthorAlias.review_status == "approved")).all():
            aliases_by_author.setdefault(alias.canonical_author_id, []).append(alias.alias)
        authors = [
            author
            for author in authors
            if needle in (author.canonical_name or author.name).casefold()
            or any(needle in alias.casefold() for alias in aliases_by_author.get(author.id or -1, []))
        ]
    if topic:
        topic_record = topic_by_query(session, topic)
        if topic_record and topic_record.review_status == "approved":
            author_ids = {
                link.author_id
                for link in session.exec(
                    select(AuthorTopic)
                    .where(AuthorTopic.topic_id == topic_record.topic_id)
                    .where(AuthorTopic.review_status == "approved")
                ).all()
            }
            authors = [author for author in authors if author.id in author_ids]
        else:
            authors = []
    rows = [row for author in authors if (row := author_card(session, author))["paper_count"] > 0]
    rows.sort(key=lambda item: (item["paper_count"], item["name"]), reverse=True)
    return {"total": len(rows), "limit": limit, "offset": offset, "items": rows[offset : offset + limit]}


def author_detail(session: Session, author_id: int) -> dict[str, Any] | None:
    author = session.get(Author, author_id)
    if (
        author is None
        or author.review_status != "approved"
        or author.identity_review_status != "approved"
        or author.identity_status != "resolved"
    ):
        return None
    papers = authored_papers(session, author)
    topics = top_topics_for_author(session, author)
    coauthors = coauthors_for(author.canonical_name or author.name, papers)
    venues = sorted({paper.venue for paper in papers if paper.venue})
    artifacts_count = session.exec(
        select(func.count())
        .select_from(PaperArtifact)
        .where(PaperArtifact.paper_id.in_([paper.paper_id for paper in papers]))
        .where(PaperArtifact.review_status == "approved")
    ).one() if papers else 0
    return {
        **author_card(session, author),
        "papers": [paper_summary(paper) for paper in sorted(papers, key=lambda item: (item.year or 0, item.title), reverse=True)],
        "topics": topics,
        "coauthors": coauthors,
        "venues": venues,
        "generated_artifacts_count": artifacts_count,
        "potential_expertise_summary": expertise_summary(author, topics, papers),
        "source_basis": "Derived only from indexed publication authorship and topic links; this does not imply availability, endorsement, supervision, or expertise beyond this corpus.",
        "review_status": author.review_status,
        "identity_review_status": author.identity_review_status,
        "identity_status": author.identity_status,
        "aliases": author_aliases(session, author),
    }


def author_card(session: Session, author: Author) -> dict[str, Any]:
    papers = authored_papers(session, author)
    topics = top_topics_for_author(session, author)[:5]
    recent = sorted(papers, key=lambda item: (item.year or 0, item.title), reverse=True)[:3]
    return {
        "author_id": author.id,
        "name": author.canonical_name or author.name,
        "paper_count": len(papers),
        "top_topics": topics,
        "recent_papers": [paper_summary(paper) for paper in recent],
        "coauthor_count": len(coauthors_for(author.canonical_name or author.name, papers)),
        "review_status": author.review_status,
        "identity_review_status": author.identity_review_status,
        "identity_status": author.identity_status,
        "source_basis": "Publication-derived evidence only; not an endorsement or statement of researcher availability.",
    }


def author_card_from_link(session: Session, link: AuthorTopic) -> dict[str, Any]:
    author = session.get(Author, link.author_id)
    return {
        "author_id": author.id if author else link.author_id,
        "name": (author.canonical_name or author.name) if author else "Unknown author",
        "paper_count": link.paper_count,
        "score": link.score,
    }


def authored_papers(session: Session, author: Author) -> list[Paper]:
    names = {normalize_author_key(author.canonical_name or author.name), normalize_author_key(author.name)}
    names.update(alias["normalized_alias"] for alias in author_aliases(session, author))
    return [
        paper
        for paper in eligible_papers(session, public=True)
        if any(normalize_author_key(name) in names for name in paper.authors)
    ]


def author_aliases(session: Session, author: Author) -> list[dict[str, Any]]:
    if author.id is None:
        return []
    aliases = session.exec(
        select(AuthorAlias)
        .where(AuthorAlias.canonical_author_id == author.id)
        .where(AuthorAlias.review_status == "approved")
        .order_by(AuthorAlias.alias)
    ).all()
    return [
        {
            "alias": alias.alias,
            "normalized_alias": alias.normalized_alias,
            "source": alias.source,
            "review_status": alias.review_status,
        }
        for alias in aliases
    ]


def top_topics_for_author(session: Session, author: Author) -> list[dict[str, Any]]:
    public_ids = {paper.paper_id for paper in authored_papers(session, author)}
    counts: dict[str, dict[str, Any]] = {}
    links = session.exec(
        select(PaperTopic)
        .where(PaperTopic.paper_id.in_(public_ids))
        .where(PaperTopic.review_status == "approved")
    ).all() if public_ids else []
    approved_author_topics = {
        link.topic_id
        for link in session.exec(
            select(AuthorTopic)
            .where(AuthorTopic.author_id == author.id)
            .where(AuthorTopic.review_status == "approved")
        ).all()
    } if author.id is not None else set()
    for link in links:
        entry = counts.setdefault(link.topic_id, {"paper_ids": set(), "score": 0.0})
        entry["paper_ids"].add(link.paper_id)
        entry["score"] += float(link.score)
    topics = []
    for topic_id, values in sorted(
        counts.items(), key=lambda item: (len(item[1]["paper_ids"]), item[1]["score"]), reverse=True
    ):
        topic = session.get(Topic, topic_id)
        if topic and topic.review_status == "approved" and topic_id in approved_author_topics:
            topics.append(
                {
                    "topic_id": topic.topic_id,
                    "name": topic.name,
                    "paper_count": len(values["paper_ids"]),
                    "score": round(values["score"], 4),
                    "evidence": {"public_paper_ids": sorted(values["paper_ids"])},
                }
            )
    return topics


def public_authors_for_topic(session: Session, paper_links: list[PaperTopic]) -> list[dict[str, Any]]:
    """Build topic authors solely from reviewed authorship on public papers."""

    papers = papers_for_links(session, paper_links)
    counts: dict[str, int] = {}
    for paper in papers:
        for name in paper.authors:
            key = normalize_author_key(name)
            if key:
                counts[key] = counts.get(key, 0) + 1
    rows: list[dict[str, Any]] = []
    for author in session.exec(
        select(Author)
        .where(Author.review_status == "approved")
        .where(Author.identity_review_status == "approved")
        .where(Author.identity_status == "resolved")
    ).all():
        identity_keys = {
            normalize_author_key(author.canonical_name or author.name),
            normalize_author_key(author.name),
        }
        identity_keys.update(alias["normalized_alias"] for alias in author_aliases(session, author))
        paper_count = sum(counts.get(key, 0) for key in identity_keys if key)
        approved_author_topic = session.exec(
            select(AuthorTopic)
            .where(AuthorTopic.author_id == author.id)
            .where(AuthorTopic.topic_id == paper_links[0].topic_id)
            .where(AuthorTopic.review_status == "approved")
        ).first() if paper_links else None
        if paper_count and approved_author_topic is not None:
            rows.append(
                {
                    "author_id": author.id,
                    "name": author.canonical_name or author.name,
                    "paper_count": paper_count,
                    "score": float(paper_count),
                }
            )
    return sorted(rows, key=lambda item: (item["paper_count"], item["name"]), reverse=True)


def coauthors_for(author_name: str, papers: list[Paper]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    author_key = normalize_author_key(author_name)
    for paper in papers:
        for coauthor in paper.authors:
            if normalize_author_key(coauthor) != author_key:
                counts[coauthor] = counts.get(coauthor, 0) + 1
    return [{"name": name, "paper_count": count} for name, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)]


def expertise_summary(author: Author, topics: list[dict[str, Any]], papers: list[Paper]) -> str:
    topic_text = ", ".join(topic["name"] for topic in topics[:4]) or "topics needing review"
    return (
        f"Within the indexed TTLAB corpus, {author.canonical_name or author.name} is listed as an author on "
        f"{len(papers)} eligible publication(s). Controlled-vocabulary links for those publications include "
        f"{topic_text}. This is bibliographic evidence only; it does not establish broader expertise, current "
        "availability, endorsement, or suitability for supervision or collaboration."
    )


def get_related_papers(session: Session, paper_id: str, *, limit: int = 5) -> list[dict[str, Any]]:
    paper = session.get(Paper, paper_id)
    if paper is None or not is_public_content(session, paper):
        return []
    all_papers = [candidate for candidate in eligible_papers(session, public=True) if candidate.paper_id != paper_id]
    base_topics = topics_for_paper(session, paper.paper_id)
    base_authors = set(paper.authors)
    feature_hashing_scores = feature_hashing_related_scores(session, paper, limit=max(limit * 4, limit))
    results: list[dict[str, Any]] = []
    for candidate in all_papers:
        candidate_topics = topics_for_paper(session, candidate.paper_id)
        shared_topics = sorted(base_topics.intersection(candidate_topics))
        shared_authors = sorted(base_authors.intersection(candidate.authors))
        reasons: list[str] = []
        source_basis: list[str] = []
        score = 0.0
        if shared_topics:
            score += len(shared_topics) * 2.0
            reasons.append("shared topic")
            source_basis.append("paper_topic_links")
        if shared_authors:
            score += len(shared_authors) * 3.0
            reasons.append("shared author")
            source_basis.append("paper.authors")
        if paper.venue and candidate.venue and paper.venue == candidate.venue:
            score += 0.7
            reasons.append("shared venue")
            source_basis.append("paper.venue")
        if paper.year and candidate.year and abs(paper.year - candidate.year) <= 2:
            score += 0.35
            reasons.append("nearby publication year")
            source_basis.append("paper.year")
        keyword_overlap = shared_keyword_overlap(paper, candidate)
        if keyword_overlap:
            score += min(keyword_overlap * 0.2, 1.0)
            reasons.append("shared title/topic keywords")
            source_basis.append("metadata_keywords")
        if candidate.paper_id in feature_hashing_scores:
            score += feature_hashing_scores[candidate.paper_id]
            reasons.append("feature-hashing retrieval similarity")
            source_basis.append("feature_hashing_index")
        if score <= 0:
            continue
        results.append(
            {
                **paper_summary(candidate),
                "score": round(score, 4),
                "reason": ", ".join(reasons),
                "shared_topics": [display_topic_name(session, topic_id) for topic_id in shared_topics],
                "shared_authors": shared_authors,
                "source_basis": sorted(set(source_basis)),
            }
        )
    return sorted(results, key=lambda item: (item["score"], item["year"] or 0, item["title"]), reverse=True)[:limit]


def feature_hashing_related_scores(session: Session, paper: Paper, *, limit: int) -> dict[str, float]:
    try:
        response = retrieve(session, paper.title, mode="feature_hashing", top_k=limit)
    except Exception:
        return {}
    scores: dict[str, float] = {}
    for result in response.get("results", []):
        other_id = result.get("paper_id")
        if other_id and other_id != paper.paper_id:
            scores[other_id] = max(scores.get(other_id, 0.0), float(result.get("scores", {}).get("vector") or 0.0))
    return scores


def topics_for_paper(session: Session, paper_id: str) -> set[str]:
    return {
        link.topic_id
        for link in session.exec(
            select(PaperTopic)
            .where(PaperTopic.paper_id == paper_id)
            .where(PaperTopic.review_status == "approved")
        ).all()
    }


def shared_keyword_overlap(left: Paper, right: Paper) -> int:
    left_terms = token_set(" ".join([left.title, " ".join(left.topics), " ".join(left.keywords)]))
    right_terms = token_set(" ".join([right.title, " ".join(right.topics), " ".join(right.keywords)]))
    return len(left_terms.intersection(right_terms))


def token_set(value: str) -> set[str]:
    return {token.lower() for token in re.findall(r"[a-zA-Z0-9]+", value) if len(token) > 3}


def paper_link_pairs(session: Session, links: list[PaperTopic]) -> list[tuple[PaperTopic, Paper]]:
    pairs: list[tuple[PaperTopic, Paper]] = []
    for link in links:
        paper = session.get(Paper, link.paper_id)
        if paper and is_public_metadata(paper):
            pairs.append((link, paper))
    return pairs


def papers_for_links(session: Session, links: list[PaperTopic]) -> list[Paper]:
    return [paper for _link, paper in paper_link_pairs(session, links)]


def paper_summary(paper: Paper) -> dict[str, Any]:
    return {
        "paper_id": paper.paper_id,
        "title": paper.title,
        "authors": paper.authors,
        "year": paper.year,
        "venue": paper.venue,
        "source_url": paper.source_url or paper.post_url,
        "pdf_url": paper.pdf_url,
    }


def trim_text(text_value: str, *, limit: int = 260) -> str:
    cleaned = re.sub(r"\s+", " ", str(text_value or "")).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip(" ,.;:") + "..."


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build and inspect deterministic TTLAB topic/author explorer data.")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("rebuild")
    show = subparsers.add_parser("show")
    show.add_argument("--topic", required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    create_db_and_tables()
    with Session(engine) as session:
        if args.command == "rebuild":
            summary = rebuild_topic_index(session)
            print(
                "topics_created={topics_created} topics_updated={topics_updated} "
                "paper_topic_links={paper_topic_links} author_topic_links={author_topic_links} "
                "skipped_reviewed_items={skipped_reviewed_items}".format(**summary)
            )
            for warning in summary["warnings"]:
                print(f"warning={warning}")
            return
        if args.command == "show":
            detail = topic_detail(session, args.topic)
            if detail is None:
                print(f"topic_not_found={args.topic}")
                return
            print(f"topic={detail['name']} papers={len(detail['papers'])} authors={len(detail['authors'])}")
            print("papers:")
            for paper in detail["papers"][:10]:
                print(f"- {paper['title']} ({paper.get('year') or 'year needs review'}) score={paper['score']}")
            print("authors:")
            for author in detail["authors"][:10]:
                print(f"- {author['name']} papers={author['paper_count']} score={author['score']}")
            return
    build_parser().print_help()


if __name__ == "__main__":
    main()
