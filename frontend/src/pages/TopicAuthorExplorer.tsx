import { useEffect, useRef, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";

import { fetchAuthorDetail, fetchAuthors, fetchExplorerOverview, fetchTopicDetail, fetchTopics, isAbortError } from "../api/client";
import { StatusBadge } from "../components/StatusBadge";
import { EmptyState, InlineProgress, ListSkeleton, MetricSkeletonGrid, SearchActionButton } from "../components/UiPrimitives";
import type { AuthorDetail, AuthorSummary, ExplorerOverview, PaperSummary, TopicDetail, TopicSummary } from "../types/paper";

type ExplorerTab = "overview" | "topics" | "authors";
const TOPIC_PAGE_SIZE = 50;
const AUTHOR_PAGE_SIZE = 50;

type TopicAuthorExplorerProps = {
  onSelectPaper: (paperId: string) => void;
  initialTab?: ExplorerTab;
  initialTopicId?: string;
  initialAuthorId?: number;
};

export function TopicAuthorExplorer({ onSelectPaper, initialTab = "overview", initialTopicId, initialAuthorId }: TopicAuthorExplorerProps) {
  const navigate = useNavigate();
  const [overview, setOverview] = useState<ExplorerOverview | null>(null);
  const [topics, setTopics] = useState<TopicSummary[]>([]);
  const [topicTotal, setTopicTotal] = useState(0);
  const [topicOffset, setTopicOffset] = useState(0);
  const [authors, setAuthors] = useState<AuthorSummary[]>([]);
  const [authorTotal, setAuthorTotal] = useState(0);
  const [authorOffset, setAuthorOffset] = useState(0);
  const [selectedTopic, setSelectedTopic] = useState<TopicDetail | null>(null);
  const [selectedAuthor, setSelectedAuthor] = useState<AuthorDetail | null>(null);
  const [topicQuery, setTopicQuery] = useState("");
  const [authorQuery, setAuthorQuery] = useState("");
  const [authorTopicFilter, setAuthorTopicFilter] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [listLoading, setListLoading] = useState<"topics" | "authors" | null>(null);
  const [detailLoading, setDetailLoading] = useState<"topic" | "author" | null>(null);
  const overviewController = useRef<AbortController | null>(null);
  const topicListController = useRef<AbortController | null>(null);
  const authorListController = useRef<AbortController | null>(null);
  const topicListSequence = useRef(0);
  const authorListSequence = useRef(0);
  const activeTab = initialTab;

  function loadOverview() {
    overviewController.current?.abort();
    const controller = new AbortController();
    overviewController.current = controller;
    const topicSequence = topicListSequence.current;
    const authorSequence = authorListSequence.current;
    setLoading(true);
    setError(null);
    Promise.all([
      fetchExplorerOverview(controller.signal),
      fetchTopics({ limit: TOPIC_PAGE_SIZE, offset: 0 }, controller.signal),
      fetchAuthors({ limit: AUTHOR_PAGE_SIZE, offset: 0 }, controller.signal),
    ])
      .then(([overviewData, topicRows, authorRows]) => {
        setOverview(overviewData);
        if (topicSequence === topicListSequence.current) {
          setTopics(topicRows.items);
          setTopicTotal(topicRows.total);
          setTopicOffset(topicRows.offset);
        }
        if (authorSequence === authorListSequence.current) {
          setAuthors(authorRows.items);
          setAuthorTotal(authorRows.total);
          setAuthorOffset(authorRows.offset);
        }
      })
      .catch((err: unknown) => {
        if (!isAbortError(err)) setError(err instanceof Error ? err.message : "Unable to load explorer data.");
      })
      .finally(() => {
        if (overviewController.current === controller) setLoading(false);
      });
  }

  useEffect(() => {
    loadOverview();
    return () => {
      overviewController.current?.abort();
      topicListController.current?.abort();
      authorListController.current?.abort();
    };
  }, []);

  useEffect(() => {
    if (!initialTopicId) {
      setSelectedTopic(null);
      return;
    }
    let active = true;
    setSelectedTopic(null);
    setDetailLoading("topic");
    setError(null);
    fetchTopicDetail(initialTopicId)
      .then((detail) => {
        if (active) setSelectedTopic(detail);
      })
      .catch((err: unknown) => {
        if (active && !isAbortError(err)) setError(err instanceof Error ? err.message : "Unable to load topic detail.");
      })
      .finally(() => {
        if (active) setDetailLoading(null);
      });
    return () => {
      active = false;
    };
  }, [initialTopicId]);

  useEffect(() => {
    if (!initialAuthorId) {
      setSelectedAuthor(null);
      return;
    }
    let active = true;
    setSelectedAuthor(null);
    setDetailLoading("author");
    setError(null);
    fetchAuthorDetail(initialAuthorId)
      .then((detail) => {
        if (active) setSelectedAuthor(detail);
      })
      .catch((err: unknown) => {
        if (active && !isAbortError(err)) setError(err instanceof Error ? err.message : "Unable to load author detail.");
      })
      .finally(() => {
        if (active) setDetailLoading(null);
      });
    return () => {
      active = false;
    };
  }, [initialAuthorId]);

  function searchTopics(offset = 0) {
    topicListController.current?.abort();
    const controller = new AbortController();
    topicListController.current = controller;
    const sequence = ++topicListSequence.current;
    setListLoading("topics");
    setError(null);
    fetchTopics({ q: topicQuery, limit: TOPIC_PAGE_SIZE, offset }, controller.signal)
      .then((rows) => {
        if (sequence === topicListSequence.current) {
          setTopics(rows.items);
          setTopicTotal(rows.total);
          setTopicOffset(rows.offset);
        }
      })
      .catch((err: unknown) => {
        if (sequence === topicListSequence.current && !isAbortError(err)) setError(err instanceof Error ? err.message : "Unable to search topics.");
      })
      .finally(() => {
        if (sequence === topicListSequence.current) setListLoading(null);
      });
  }

  function searchAuthors(offset = 0) {
    authorListController.current?.abort();
    const controller = new AbortController();
    authorListController.current = controller;
    const sequence = ++authorListSequence.current;
    setListLoading("authors");
    setError(null);
    fetchAuthors({ q: authorQuery, topic: authorTopicFilter, limit: AUTHOR_PAGE_SIZE, offset }, controller.signal)
      .then((rows) => {
        if (sequence === authorListSequence.current) {
          setAuthors(rows.items);
          setAuthorTotal(rows.total);
          setAuthorOffset(rows.offset);
        }
      })
      .catch((err: unknown) => {
        if (sequence === authorListSequence.current && !isAbortError(err)) setError(err instanceof Error ? err.message : "Unable to search authors.");
      })
      .finally(() => {
        if (sequence === authorListSequence.current) setListLoading(null);
      });
  }

  function openTopic(topicId: string) {
    navigate(`/explorer/topics/${encodeURIComponent(topicId)}`);
  }

  function openAuthor(authorId: number) {
    navigate(`/explorer/authors/${authorId}`);
  }

  return (
    <section className="page-section" aria-labelledby="explorer-title">
      <h2 id="explorer-title" className="sr-only">Topic and author explorer</h2>
      <p className="notice">
        Topic and author relationships are deterministic and source-derived from indexed papers, chunks, and artifacts. They are not manually verified unless reviewed.
      </p>
      {error ? (
        <div className="notice notice--error" role="alert">
          <p>{error}</p>
          <button className="action-button" onClick={loadOverview}>Retry explorer data</button>
        </div>
      ) : null}
      {loading && !overview ? <InlineProgress label="Loading explorer overview, topics, and authors..." /> : null}

      <nav className="artifact-tabs explorer-tabs" aria-label="Explorer sections">
        <NavLink end className={({ isActive }) => isActive ? "active" : ""} to="/explorer">
          Overview
        </NavLink>
        <NavLink className={({ isActive }) => isActive ? "active" : ""} to="/explorer/topics">
          Topics
        </NavLink>
        <NavLink className={({ isActive }) => isActive ? "active" : ""} to="/explorer/authors">
          Authors
        </NavLink>
      </nav>

      {activeTab === "overview" && loading && !overview ? <ExplorerOverviewSkeleton /> : null}
      {activeTab === "overview" && overview ? (
        <ExplorerOverviewPanel overview={overview} onOpenTopic={openTopic} onOpenAuthor={openAuthor} onSelectPaper={onSelectPaper} />
      ) : null}
      {activeTab === "topics" ? (
        <TopicBrowser
          topics={topics}
          query={topicQuery}
          selectedTopic={selectedTopic}
          loading={loading || listLoading === "topics"}
          detailLoading={detailLoading === "topic"}
          total={topicTotal}
          offset={topicOffset}
          pageSize={TOPIC_PAGE_SIZE}
          onQueryChange={setTopicQuery}
          onSearch={searchTopics}
          onPageChange={searchTopics}
          onOpenTopic={openTopic}
          onSelectPaper={onSelectPaper}
        />
      ) : null}
      {activeTab === "authors" ? (
        <AuthorBrowser
          authors={authors}
          query={authorQuery}
          topicFilter={authorTopicFilter}
          selectedAuthor={selectedAuthor}
          loading={loading || listLoading === "authors"}
          detailLoading={detailLoading === "author"}
          total={authorTotal}
          offset={authorOffset}
          pageSize={AUTHOR_PAGE_SIZE}
          onQueryChange={setAuthorQuery}
          onTopicFilterChange={setAuthorTopicFilter}
          onSearch={searchAuthors}
          onPageChange={searchAuthors}
          onOpenAuthor={openAuthor}
          onSelectPaper={onSelectPaper}
        />
      ) : null}
    </section>
  );
}

function ExplorerOverviewSkeleton() {
  return (
    <>
      <MetricSkeletonGrid count={6} />
      <div className="explorer-columns">
        <ListSkeleton count={3} lines={2} />
        <ListSkeleton count={3} lines={2} />
      </div>
    </>
  );
}

function ExplorerOverviewPanel({
  overview,
  onOpenTopic,
  onOpenAuthor,
  onSelectPaper,
}: {
  overview: ExplorerOverview;
  onOpenTopic: (topicId: string) => void;
  onOpenAuthor: (authorId: number) => void;
  onSelectPaper: (paperId: string) => void;
}) {
  return (
    <>
      <div className="metrics-grid">
        <Metric label="Topics" value={overview.topic_count} />
        <Metric label="Authors" value={overview.author_count} />
        <Metric label="Papers" value={overview.paper_count} />
        <Metric label="Paper-topic links" value={overview.linked_paper_topics} />
        <Metric label="Author-topic links" value={overview.linked_author_topics} />
        <article className="metric">
          <span className="metric__label">Explorer index</span>
          <strong className="metric__small">{overview.explorer_index_status}</strong>
        </article>
      </div>
      {overview.explorer_index_status !== "ready" ? (
        <EmptyState
          title="No topics are approved for public exploration yet"
          body="Topics appear here only when their source papers pass publication, rights, and public-access review."
        />
      ) : null}
      <div className="explorer-columns">
        <section>
          <h2>Top Topics</h2>
          <div className="paper-list">
            {overview.top_topics.map((topic) => (
              <TopicCard key={topic.topic_id} topic={topic} onOpenTopic={onOpenTopic} onSelectPaper={onSelectPaper} />
            ))}
          </div>
        </section>
        <section>
          <h2>Top Authors</h2>
          <div className="paper-list">
            {overview.top_authors.map((author) => (
              <AuthorCard key={author.author_id} author={author} onOpenAuthor={onOpenAuthor} onSelectPaper={onSelectPaper} />
            ))}
          </div>
        </section>
      </div>
    </>
  );
}

function TopicBrowser({
  topics,
  query,
  selectedTopic,
  loading,
  detailLoading,
  total,
  offset,
  pageSize,
  onQueryChange,
  onSearch,
  onPageChange,
  onOpenTopic,
  onSelectPaper,
}: {
  topics: TopicSummary[];
  query: string;
  selectedTopic: TopicDetail | null;
  loading: boolean;
  detailLoading: boolean;
  total: number;
  offset: number;
  pageSize: number;
  onQueryChange: (value: string) => void;
  onSearch: (offset?: number) => void;
  onPageChange: (offset: number) => void;
  onOpenTopic: (topicId: string) => void;
  onSelectPaper: (paperId: string) => void;
}) {
  return (
    <div className="explorer-layout">
      <section>
        <form className="search-toolbar explorer-toolbar" aria-busy={loading} onSubmit={(event) => { event.preventDefault(); onSearch(0); }}>
          <label className="field-label" htmlFor="topic-search">Search topics</label>
          <input id="topic-search" value={query} onChange={(event) => onQueryChange(event.target.value)} placeholder="For example: networks" />
          <SearchActionButton type="submit" busy={loading} />
        </form>
        <div className="paper-list">
          {loading ? <ListSkeleton count={4} lines={2} /> : null}
          {!loading && topics.map((topic) => (
            <TopicCard key={topic.topic_id} topic={topic} onOpenTopic={onOpenTopic} onSelectPaper={onSelectPaper} />
          ))}
          {!loading && !topics.length ? (
            <EmptyState
              title="No approved public topics found"
              body="Try a broader topic search. Hidden or rights-restricted review records are never used as a public fallback."
            />
          ) : null}
        </div>
        {!loading && total > 0 ? (
          <nav className="pagination-controls" aria-label="Topic results pagination">
            <p>Showing {offset + 1}–{Math.min(offset + pageSize, total)} of {total} topics</p>
            <div>
              <button className="action-button action-button--secondary" disabled={offset === 0} onClick={() => onPageChange(Math.max(0, offset - pageSize))}>Previous</button>
              <button className="action-button action-button--secondary" disabled={offset + pageSize >= total} onClick={() => onPageChange(offset + pageSize)}>Next</button>
            </div>
          </nav>
        ) : null}
      </section>
      <section>
        {detailLoading ? <ListSkeleton count={1} lines={5} /> : selectedTopic ? (
          <TopicDetailPanel topic={selectedTopic} onOpenTopic={onOpenTopic} onSelectPaper={onSelectPaper} />
        ) : (
          <EmptyState title="Open a topic" body="Inspect papers, authors, related topics, and source evidence for the selected topic." />
        )}
      </section>
    </div>
  );
}

function AuthorBrowser({
  authors,
  query,
  topicFilter,
  selectedAuthor,
  loading,
  detailLoading,
  total,
  offset,
  pageSize,
  onQueryChange,
  onTopicFilterChange,
  onSearch,
  onPageChange,
  onOpenAuthor,
  onSelectPaper,
}: {
  authors: AuthorSummary[];
  query: string;
  topicFilter: string;
  selectedAuthor: AuthorDetail | null;
  loading: boolean;
  detailLoading: boolean;
  total: number;
  offset: number;
  pageSize: number;
  onQueryChange: (value: string) => void;
  onTopicFilterChange: (value: string) => void;
  onSearch: (offset?: number) => void;
  onPageChange: (offset: number) => void;
  onOpenAuthor: (authorId: number) => void;
  onSelectPaper: (paperId: string) => void;
}) {
  return (
    <div className="explorer-layout">
      <section>
        <form className="search-toolbar explorer-toolbar explorer-toolbar--authors" aria-busy={loading} onSubmit={(event) => { event.preventDefault(); onSearch(0); }}>
          <label className="field-label" htmlFor="author-search">Search authors</label>
          <input id="author-search" value={query} onChange={(event) => onQueryChange(event.target.value)} placeholder="For example: Hosein" />
          <label className="field-label" htmlFor="author-topic-filter">Filter authors by topic</label>
          <input id="author-topic-filter" value={topicFilter} onChange={(event) => onTopicFilterChange(event.target.value)} placeholder="For example: optimization" />
          <SearchActionButton type="submit" busy={loading} />
        </form>
        <div className="paper-list">
          {loading ? <ListSkeleton count={4} lines={2} /> : null}
          {!loading && authors.map((author) => (
            <AuthorCard key={author.author_id} author={author} onOpenAuthor={onOpenAuthor} onSelectPaper={onSelectPaper} />
          ))}
          {!loading && !authors.length ? <EmptyState title="No authors found" body="Try clearing the topic filter or searching a broader name fragment." /> : null}
        </div>
        {!loading && total > 0 ? (
          <nav className="pagination-controls" aria-label="Author results pagination">
            <p>Showing {offset + 1}–{Math.min(offset + pageSize, total)} of {total} authors</p>
            <div>
              <button className="action-button action-button--secondary" disabled={offset === 0} onClick={() => onPageChange(Math.max(0, offset - pageSize))}>Previous</button>
              <button className="action-button action-button--secondary" disabled={offset + pageSize >= total} onClick={() => onPageChange(offset + pageSize)}>Next</button>
            </div>
          </nav>
        ) : null}
      </section>
      <section>
        {detailLoading ? <ListSkeleton count={1} lines={5} /> : selectedAuthor ? (
          <AuthorDetailPanel author={selectedAuthor} onSelectPaper={onSelectPaper} />
        ) : (
          <EmptyState title="Open an author" body="Inspect indexed papers, topics, coauthors, venues, and source-derived expertise." />
        )}
      </section>
    </div>
  );
}

function TopicCard({
  topic,
  onOpenTopic,
  onSelectPaper,
}: {
  topic: TopicSummary;
  onOpenTopic: (topicId: string) => void;
  onSelectPaper: (paperId: string) => void;
}) {
  return (
    <article className="explorer-card">
      <div>
        <div className="paper-card__meta">
          <span>{topic.paper_count} papers</span>
          <span>{topic.author_count} authors</span>
        </div>
        <h3>{topic.name}</h3>
        <p>{topic.description ?? "Deterministically inferred topic."}</p>
        <SmallPaperLinks papers={topic.sample_papers} onSelectPaper={onSelectPaper} />
      </div>
      <button className="action-button" onClick={() => onOpenTopic(topic.topic_id)}>
        Open Topic
      </button>
    </article>
  );
}

function TopicDetailPanel({
  topic,
  onOpenTopic,
  onSelectPaper,
}: {
  topic: TopicDetail;
  onOpenTopic: (topicId: string) => void;
  onSelectPaper: (paperId: string) => void;
}) {
  return (
    <article className="admin-card">
      <div className="paper-card__badges paper-card__badges--left">
        <StatusBadge label={topic.review_status} />
        <StatusBadge label={`${topic.paper_count} papers`} tone="good" />
      </div>
      <h2>{topic.name}</h2>
      <p>{topic.description}</p>
      <section>
        <h3>Papers</h3>
        <div className="paper-list">
          {topic.papers.map((paper) => (
            <article className="citation-card" key={paper.paper_id}>
              <div className="paper-card__meta">
                <span>{paper.year ?? "Year needs review"}</span>
                <span>Score {paper.score.toFixed(2)}</span>
              </div>
              <h3>{paper.title}</h3>
              <p>{paper.authors.join(", ") || "Authors need review"}</p>
              <button className="link-button" onClick={() => onSelectPaper(paper.paper_id)}>
                Open paper
              </button>
              <EvidenceList evidence={paper.evidence} />
            </article>
          ))}
        </div>
      </section>
      <section>
        <h3>Authors</h3>
        <div className="chip-row">
          {topic.authors.map((author) => (
            <span key={author.author_id}>{author.name}</span>
          ))}
        </div>
      </section>
      <section>
        <h3>Related Topics</h3>
        <div className="chip-row">
          {topic.related_topics.map((related) => (
            <button className="chip-button" key={related.topic_id} onClick={() => onOpenTopic(related.topic_id)}>
              {related.name} ({related.shared_paper_count})
            </button>
          ))}
          {!topic.related_topics.length ? <span>No related topics found</span> : null}
        </div>
      </section>
    </article>
  );
}

function AuthorCard({
  author,
  onOpenAuthor,
  onSelectPaper,
}: {
  author: AuthorSummary;
  onOpenAuthor: (authorId: number) => void;
  onSelectPaper: (paperId: string) => void;
}) {
  return (
    <article className="explorer-card">
      <div>
        <div className="paper-card__meta">
          <span>{author.paper_count} papers</span>
          <span>{author.coauthor_count ?? 0} coauthors</span>
        </div>
        <h3>{author.name}</h3>
        <div className="chip-row chip-row--compact">
          {(author.top_topics ?? []).slice(0, 4).map((topic) => (
            <span key={topic.topic_id}>{topic.name}</span>
          ))}
        </div>
        <SmallPaperLinks papers={author.recent_papers ?? []} onSelectPaper={onSelectPaper} />
      </div>
      <button className="action-button" onClick={() => onOpenAuthor(author.author_id)}>
        Open Author
      </button>
    </article>
  );
}

function AuthorDetailPanel({ author, onSelectPaper }: { author: AuthorDetail; onSelectPaper: (paperId: string) => void }) {
  return (
    <article className="admin-card">
      <div className="paper-card__badges paper-card__badges--left">
        <StatusBadge label={author.review_status ?? "needs_review"} />
        <StatusBadge label={`${author.paper_count} papers`} tone="good" />
      </div>
      <h2>{author.name}</h2>
      <p>{author.potential_expertise_summary}</p>
      <p className="notice notice--warning">{author.source_basis}</p>
      <section>
        <h3>Top Topics</h3>
        <div className="chip-row">
          {author.top_topics?.map((topic) => (
            <span key={topic.topic_id}>{topic.name}</span>
          ))}
        </div>
      </section>
      <section>
        <h3>Papers</h3>
        <SmallPaperLinks papers={author.papers} onSelectPaper={onSelectPaper} />
      </section>
      <section>
        <h3>Coauthors</h3>
        <div className="chip-row">
          {author.coauthors.map((coauthor) => (
            <span key={coauthor.name}>{coauthor.name} ({coauthor.paper_count})</span>
          ))}
          {!author.coauthors.length ? <span>No coauthors found</span> : null}
        </div>
      </section>
      <section>
        <h3>Venues</h3>
        <div className="chip-row">
          {author.venues.map((venue) => (
            <span key={venue}>{venue}</span>
          ))}
          {!author.venues.length ? <span>Venues need review</span> : null}
        </div>
      </section>
    </article>
  );
}

function SmallPaperLinks({ papers, onSelectPaper }: { papers: PaperSummary[]; onSelectPaper: (paperId: string) => void }) {
  if (!papers.length) {
    return <EmptyState title="No papers linked yet" />;
  }
  return (
    <div className="paper-mini-list">
      {papers.map((paper) => (
        <button className="link-button paper-mini-link" key={paper.paper_id} onClick={() => onSelectPaper(paper.paper_id)}>
          {paper.title}
        </button>
      ))}
    </div>
  );
}

function EvidenceList({ evidence }: { evidence: TopicDetail["papers"][number]["evidence"] }) {
  if (!evidence.length) {
    return null;
  }
  return (
    <details className="retrieved-details">
      <summary>Evidence</summary>
      <div className="paper-list">
        {evidence.slice(0, 4).map((item, index) => (
          <article className="citation-card" key={`${item.source}-${index}`}>
            <div className="paper-card__meta">
              <span>{item.source ?? "source"}</span>
              {item.chunk_id ? <span>{item.chunk_id}</span> : null}
            </div>
            <p>{item.text ?? item.paper_title ?? "Evidence recorded."}</p>
          </article>
        ))}
      </div>
    </details>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <article className="metric">
      <span className="metric__label">{label}</span>
      <strong>{value}</strong>
    </article>
  );
}
