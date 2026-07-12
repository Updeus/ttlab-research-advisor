from __future__ import annotations

import argparse
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete
from sqlmodel import Session, desc, func, select

from app.db import create_db_and_tables, engine
from app.indexing.retriever import retrieve
from app.ingestion.metadata_cleaner import active_author_for_name, ensure_author_identity, normalize_author_key
from app.models import Author, AuthorAlias, AuthorTopic, Chunk, Paper, PaperArtifact, PaperTopic, Topic

REVIEWED_STATUSES = {"reviewed", "approved"}
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
    ("rag", ("retrieval augmented generation", "retrieval-augmented generation", " rag ")),
    ("ai", ("artificial intelligence", " ai ", "intelligent system")),
    ("machine learning", ("machine learning", " ml ", "classification", "neural", "deep learning")),
    ("information retrieval", ("retrieval", "search engine", "ranking", "relevance")),
    ("data science", ("data science", "data analysis", "data-driven", "dataset", "benchmark")),
    ("research discovery", ("research discovery", "academic discovery", "publication", "paper evidence")),
    ("web applications", ("web application", "web app", "dashboard", "api", "frontend")),
    ("open data", ("open data", "data portal", "real time data", "repository")),
    ("education", ("education", "student", "learning", "teaching")),
    ("optimization", ("optimization", "optimisation", "linear programming", "integer programming")),
    ("iot", ("internet of things", " iot ", "sensor", "sensors")),
    ("agriculture", ("agriculture", "agricultural", "crop", "farming")),
    ("climate", ("climate", "weather", "rainfall", "temperature")),
    ("telecommunications", ("telecommunication", "telecom", "wireless", "cellular")),
    ("mobile services", ("mobile data", "mobile service", "m-commerce", "esim", "quality of service", " qos ")),
    ("networks", ("network", "networks", "routing", "traffic flow")),
    ("visualization", ("visualization", "visualisation", "dashboard", "chart", "graph")),
    ("natural language processing", ("natural language", "nlp", "language model", "text mining")),
    ("summarization", ("summarization", "summarisation", "summary", "summarize")),
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
    ("recommendation systems", ("playlist", "recommendation", "shuffle", "sequencing")),
    ("e-commerce", ("e-commerce", "commerce", "m-commerce")),
    ("supply chain", ("delivery", "deliveries", "product deliver")),
    ("smart grid", ("smart meter", "meter readings")),
    ("body shape detection", ("body shape", "shape detection")),
    ("civil society", ("civil society", "data4good")),
    ("internet resilience", ("internet resilience", "small island")),
    ("simulation", ("simulation", "simulator", "simulate")),
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
    papers = list(session.exec(select(Paper).order_by(Paper.title)).all())
    session.execute(delete(PaperTopic))
    session.execute(delete(AuthorTopic))
    session.commit()

    existing_topics = {topic.normalized_name: topic for topic in session.exec(select(Topic)).all()}
    summary = {
        "topics_created": 0,
        "topics_updated": 0,
        "paper_topic_links": 0,
        "author_topic_links": 0,
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
            session.add(link)
            summary["paper_topic_links"] += 1
    session.commit()

    update_topic_descriptions(session)
    summary["author_topic_links"] = rebuild_author_topics(session)
    session.commit()
    return summary


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
    candidates: dict[str, TopicCandidate] = {}
    for topic in paper.topics:
        add_candidate(candidates, topic, score=2.8, source="paper_topics", text=f"Paper topic: {topic}", field="paper.topics")
    for keyword in paper.keywords:
        add_candidate(candidates, keyword, score=1.6, source="paper_keywords", text=f"Paper keyword: {keyword}", field="paper.keywords")

    infer_topics_from_text(candidates, paper.title, score=1.0, source="paper_title", field="title")
    if paper.venue:
        infer_topics_from_text(candidates, paper.venue, score=0.4, source="venue", field="venue")

    chunks = session.exec(
        select(Chunk).where(Chunk.paper_id == paper.paper_id).order_by(Chunk.chunk_index).limit(10)
    ).all()
    for chunk in chunks:
        if chunk.section:
            infer_topics_from_text(
                candidates,
                chunk.section,
                score=0.35,
                source="chunk_section",
                field="chunk.section",
                chunk_id=chunk.chunk_id,
            )
        infer_topics_from_text(
            candidates,
            chunk.text[:1600],
            score=0.55,
            source="chunk_text",
            field="chunk.text",
            chunk_id=chunk.chunk_id,
        )

    artifacts = session.exec(
        select(PaperArtifact)
        .where(PaperArtifact.paper_id == paper.paper_id)
        .where(PaperArtifact.generation_status == "generated")
        .order_by(desc(PaperArtifact.created_at))
        .limit(8)
    ).all()
    for artifact in artifacts:
        for text_value in artifact_topic_texts(artifact):
            infer_topics_from_text(
                candidates,
                text_value,
                score=0.85,
                source=f"artifact:{artifact.artifact_type}",
                field="artifact.generated_json",
                artifact_id=artifact.artifact_id,
            )
    return candidates


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
    searchable = f" {re.sub(r'[^a-z0-9+# ]+', ' ', text_value.lower())} "
    for normalized_name, terms in TOPIC_RULES:
        if any(term in searchable for term in terms):
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


def artifact_topic_texts(artifact: PaperArtifact) -> list[str]:
    payload = artifact.corrected_json if artifact.corrected_json else artifact.generated_json
    texts: list[str] = []
    if artifact.generated_text:
        texts.append(artifact.generated_text)
    texts.extend(recursive_text_values(payload, preferred_keys={"skills", "summary", "text", "title", "basis"}))
    return [text for text in texts if text]


def recursive_text_values(value: Any, *, preferred_keys: set[str]) -> list[str]:
    texts: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in preferred_keys and isinstance(child, str):
                texts.append(child)
            elif key == "skills" and isinstance(child, list):
                texts.extend(str(item) for item in child)
            else:
                texts.extend(recursive_text_values(child, preferred_keys=preferred_keys))
    elif isinstance(value, list):
        for child in value:
            texts.extend(recursive_text_values(child, preferred_keys=preferred_keys))
    return texts


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
        topic.name = candidate.name
        topic.updated_at = now
        summary["topics_updated"] += 1
    session.add(topic)
    return topic


def update_topic_descriptions(session: Session) -> None:
    for topic in session.exec(select(Topic)).all():
        paper_count = session.exec(
            select(func.count()).select_from(PaperTopic).where(PaperTopic.topic_id == topic.topic_id)
        ).one()
        topic.description = f"Deterministically linked to {paper_count} indexed TTLAB paper(s)."
        topic.updated_at = utc_now()
        session.add(topic)
    session.commit()


def rebuild_author_topics(session: Session) -> int:
    papers = list(session.exec(select(Paper)).all())
    paper_topics = list(session.exec(select(PaperTopic)).all())
    links_by_paper: dict[str, list[PaperTopic]] = {}
    for link in paper_topics:
        links_by_paper.setdefault(link.paper_id, []).append(link)

    link_count = 0
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
            session.add(
                AuthorTopic(
                    link_id=f"{author.id}:{topic_id}",
                    author_id=author.id,
                    topic_id=topic_id,
                    paper_count=len(entry["papers"]),
                    score=round(float(entry["score"]), 4),
                    evidence_json=entry["evidence"],
                    created_at=utc_now(),
                )
            )
            link_count += 1
    return link_count


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
    topics = list(session.exec(select(Topic).order_by(Topic.name)).all())
    authors = list(
        session.exec(
            select(Author).where(Author.identity_status.notin_(["merged", "invalid"])).order_by(Author.name)
        ).all()
    )
    papers = list(session.exec(select(Paper).order_by(Paper.year.desc(), Paper.title)).all())
    paper_topic_count = session.exec(select(func.count()).select_from(PaperTopic)).one()
    author_topic_count = session.exec(select(func.count()).select_from(AuthorTopic)).one()
    return {
        "topic_count": len(topics),
        "author_count": len(authors),
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
    topics = list(session.exec(select(Topic).order_by(Topic.name)).all())
    rows = [topic_card(session, topic) for topic in topics]
    if q:
        needle = q.lower()
        rows = [row for row in rows if needle in row["name"].lower() or needle in row["normalized_name"]]
    if min_papers is not None:
        rows = [row for row in rows if row["paper_count"] >= min_papers]
    rows.sort(key=lambda item: (item["paper_count"], item["author_count"], item["name"]), reverse=True)
    return {"total": len(rows), "limit": limit, "offset": offset, "items": rows[offset : offset + limit]}


def topic_card(session: Session, topic: Topic) -> dict[str, Any]:
    paper_links = list(session.exec(select(PaperTopic).where(PaperTopic.topic_id == topic.topic_id)).all())
    author_links = list(session.exec(select(AuthorTopic).where(AuthorTopic.topic_id == topic.topic_id)).all())
    top_authors = [
        author_card_from_link(session, link)
        for link in sorted(author_links, key=lambda item: (item.paper_count, item.score), reverse=True)[:4]
    ]
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
        "author_count": len({link.author_id for link in author_links}),
        "top_authors": top_authors,
        "sample_papers": sample_papers,
        "review_status": topic.review_status,
    }


def topic_detail(session: Session, topic_id: str) -> dict[str, Any] | None:
    topic = session.get(Topic, topic_id) or topic_by_query(session, topic_id)
    if topic is None:
        return None
    paper_links = list(session.exec(select(PaperTopic).where(PaperTopic.topic_id == topic.topic_id)).all())
    author_links = list(session.exec(select(AuthorTopic).where(AuthorTopic.topic_id == topic.topic_id)).all())
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
        "authors": [
            author_card_from_link(session, link)
            for link in sorted(author_links, key=lambda item: (item.paper_count, item.score), reverse=True)
        ],
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
    for link in session.exec(select(PaperTopic).where(PaperTopic.paper_id.in_(list(paper_ids)))).all() if paper_ids else []:
        if link.topic_id == topic_id:
            continue
        counts[link.topic_id] = counts.get(link.topic_id, 0) + 1
    related = []
    for other_topic_id, shared_papers in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:8]:
        topic = session.get(Topic, other_topic_id)
        if topic:
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
            select(Author).where(Author.identity_status.notin_(["merged", "invalid"])).order_by(Author.name)
        ).all()
    )
    if q:
        needle = q.casefold()
        aliases_by_author: dict[int, list[str]] = {}
        for alias in session.exec(select(AuthorAlias)).all():
            aliases_by_author.setdefault(alias.canonical_author_id, []).append(alias.alias)
        authors = [
            author
            for author in authors
            if needle in (author.canonical_name or author.name).casefold()
            or any(needle in alias.casefold() for alias in aliases_by_author.get(author.id or -1, []))
        ]
    if topic:
        topic_record = topic_by_query(session, topic)
        if topic_record:
            author_ids = {
                link.author_id
                for link in session.exec(select(AuthorTopic).where(AuthorTopic.topic_id == topic_record.topic_id)).all()
            }
            authors = [author for author in authors if author.id in author_ids]
        else:
            authors = []
    rows = [author_card(session, author) for author in authors]
    rows.sort(key=lambda item: (item["paper_count"], item["name"]), reverse=True)
    return {"total": len(rows), "limit": limit, "offset": offset, "items": rows[offset : offset + limit]}


def author_detail(session: Session, author_id: int) -> dict[str, Any] | None:
    author = session.get(Author, author_id)
    if author is None:
        return None
    papers = authored_papers(session, author)
    topics = top_topics_for_author(session, author)
    coauthors = coauthors_for(author.canonical_name or author.name, papers)
    venues = sorted({paper.venue for paper in papers if paper.venue})
    artifacts_count = session.exec(
        select(func.count())
        .select_from(PaperArtifact)
        .where(PaperArtifact.paper_id.in_([paper.paper_id for paper in papers]))
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
        for paper in session.exec(select(Paper)).all()
        if any(normalize_author_key(name) in names for name in paper.authors)
    ]


def author_aliases(session: Session, author: Author) -> list[dict[str, Any]]:
    if author.id is None:
        return []
    aliases = session.exec(
        select(AuthorAlias).where(AuthorAlias.canonical_author_id == author.id).order_by(AuthorAlias.alias)
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
    if author.id is None:
        return []
    links = session.exec(select(AuthorTopic).where(AuthorTopic.author_id == author.id)).all()
    topics = []
    for link in sorted(links, key=lambda item: (item.paper_count, item.score), reverse=True):
        topic = session.get(Topic, link.topic_id)
        if topic:
            topics.append(
                {
                    "topic_id": topic.topic_id,
                    "name": topic.name,
                    "paper_count": link.paper_count,
                    "score": link.score,
                    "evidence": link.evidence_json,
                }
            )
    return topics


def coauthors_for(author_name: str, papers: list[Paper]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for paper in papers:
        for coauthor in paper.authors:
            if coauthor != author_name:
                counts[coauthor] = counts.get(coauthor, 0) + 1
    return [{"name": name, "paper_count": count} for name, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)]


def expertise_summary(author: Author, topics: list[dict[str, Any]], papers: list[Paper]) -> str:
    topic_text = ", ".join(topic["name"] for topic in topics[:4]) or "topics needing review"
    return (
        f"Potential researcher fit based on authorship and indexed paper topics: {author.canonical_name or author.name} has "
        f"{len(papers)} indexed TTLAB paper(s), with recurring topics including {topic_text}. "
        "This is derived from indexed records, not verified supervisor availability."
    )


def get_related_papers(session: Session, paper_id: str, *, limit: int = 5) -> list[dict[str, Any]]:
    paper = session.get(Paper, paper_id)
    if paper is None:
        return []
    all_papers = [candidate for candidate in session.exec(select(Paper)).all() if candidate.paper_id != paper_id]
    base_topics = topics_for_paper(session, paper.paper_id)
    base_authors = set(paper.authors)
    semantic_scores = semantic_related_scores(session, paper, limit=max(limit * 4, limit))
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
        if candidate.paper_id in semantic_scores:
            score += semantic_scores[candidate.paper_id]
            reasons.append("semantic retrieval similarity")
            source_basis.append("hashing_semantic_index")
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


def semantic_related_scores(session: Session, paper: Paper, *, limit: int) -> dict[str, float]:
    try:
        response = retrieve(session, paper.title, mode="semantic", top_k=limit)
    except Exception:
        return {}
    scores: dict[str, float] = {}
    for result in response.get("results", []):
        other_id = result.get("paper_id")
        if other_id and other_id != paper.paper_id:
            scores[other_id] = max(scores.get(other_id, 0.0), float(result.get("scores", {}).get("semantic") or 0.0))
    return scores


def topics_for_paper(session: Session, paper_id: str) -> set[str]:
    return {
        link.topic_id
        for link in session.exec(select(PaperTopic).where(PaperTopic.paper_id == paper_id)).all()
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
        if paper:
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
