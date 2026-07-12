import { useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";

import {
  fetchAdminOverview,
  fetchReviewEvents,
  fetchReviewQueue,
  patchAdminPaper,
  reviewAnswer,
  reviewArtifact,
  reviewRecommendation,
} from "../api/client";
import { StatusBadge } from "../components/StatusBadge";
import { BusyButton, EmptyState, ListSkeleton, MetricSkeletonGrid } from "../components/UiPrimitives";
import type { ToastTone } from "../components/UiPrimitives";
import type { AdminOverview, Paper, ReviewEvent, ReviewQueueItem, ReviewStatus } from "../types/paper";

type AdminTab = "overview" | "queue" | "paper" | "artifacts" | "answers" | "recommendations" | "events";

type AdminReviewPageProps = {
  papers: Paper[];
  onSelectPaper: (paperId: string) => void;
  onNotify?: (message: string, tone?: ToastTone) => void;
};

const ADMIN_TABS: { id: AdminTab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "queue", label: "Review Queue" },
  { id: "paper", label: "Paper Metadata" },
  { id: "artifacts", label: "Artifacts" },
  { id: "answers", label: "Ask Answers" },
  { id: "recommendations", label: "Recommendations" },
  { id: "events", label: "Review Events" },
];

const REVIEW_STATUSES: ReviewStatus[] = ["needs_review", "ai_reviewed", "reviewed", "approved", "rejected", "needs_reprocess"];

export function AdminReviewPage({ papers, onSelectPaper, onNotify }: AdminReviewPageProps) {
  const [activeTab, setActiveTab] = useState<AdminTab>("overview");
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [queue, setQueue] = useState<ReviewQueueItem[]>([]);
  const [queueTotal, setQueueTotal] = useState(0);
  const [events, setEvents] = useState<ReviewEvent[]>([]);
  const [selectedItem, setSelectedItem] = useState<ReviewQueueItem | null>(null);
  const [itemType, setItemType] = useState("");
  const [reviewStatus, setReviewStatus] = useState("needs_review");
  const [groundingStatus, setGroundingStatus] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);

  function refresh() {
    setLoading(true);
    setError(null);
    Promise.all([
      fetchAdminOverview(),
      fetchReviewQueue({
        item_type: itemType || undefined,
        review_status: reviewStatus || undefined,
        grounding_status: groundingStatus || undefined,
        limit: 50,
      }),
      fetchReviewEvents({ limit: 30 }),
    ])
      .then(([overviewData, queueData, eventRows]) => {
        setOverview(overviewData);
        setQueue(queueData.items);
        setQueueTotal(queueData.total);
        setEvents(eventRows);
        if (!selectedItem && queueData.items.length) {
          setSelectedItem(queueData.items[0]);
        }
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Unable to load admin review data."))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    refresh();
    // Filters intentionally trigger a fresh queue; refresh is small and local.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [itemType, reviewStatus, groundingStatus]);

  function chooseItem(item: ReviewQueueItem) {
    setSelectedItem(item);
    setActiveTab(tabForItem(item.item_type));
  }

  function completeAction(text: string) {
    onNotify?.(text, "success");
    refresh();
  }

  function failAction(err: unknown) {
    const text = err instanceof Error ? err.message : "Admin review action failed.";
    setError(text);
    onNotify?.(text, "error");
  }

  function handleTabKey(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    let next = index;
    if (event.key === "ArrowRight") next = (index + 1) % ADMIN_TABS.length;
    else if (event.key === "ArrowLeft") next = (index - 1 + ADMIN_TABS.length) % ADMIN_TABS.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = ADMIN_TABS.length - 1;
    else return;
    event.preventDefault();
    setActiveTab(ADMIN_TABS[next].id);
    tabRefs.current[next]?.focus();
  }

  return (
    <section className="page-section" aria-labelledby="admin-review-title">
      <h2 id="admin-review-title" className="sr-only">Admin review</h2>
      <p className="notice">Protected reviewer tools. Review actions are attributed by the authenticated actor and recorded as append-only audit events.</p>
      {error ? (
        <div className="notice notice--error" role="alert">
          <p>{error}</p>
          <button className="action-button" onClick={refresh}>Retry protected data</button>
        </div>
      ) : null}

      <div className="artifact-tabs admin-tabs" role="tablist" aria-label="Admin review sections">
        {ADMIN_TABS.map((tab, index) => (
          <button
            key={tab.id}
            ref={(node) => { tabRefs.current[index] = node; }}
            id={`admin-tab-${tab.id}`}
            role="tab"
            aria-controls={`admin-panel-${tab.id}`}
            aria-selected={activeTab === tab.id}
            tabIndex={activeTab === tab.id ? 0 : -1}
            className={activeTab === tab.id ? "active" : ""}
            onClick={() => setActiveTab(tab.id)}
            onKeyDown={(event) => handleTabKey(event, index)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div role="tabpanel" id={`admin-panel-${activeTab}`} aria-labelledby={`admin-tab-${activeTab}`} tabIndex={0}>
      {activeTab === "overview" ? <AdminOverviewPanel overview={overview} loading={loading} /> : null}
      {activeTab === "queue" ? (
        <ReviewQueuePanel
          queue={queue}
          total={queueTotal}
          itemType={itemType}
          reviewStatus={reviewStatus}
          groundingStatus={groundingStatus}
          loading={loading}
          onItemTypeChange={setItemType}
          onReviewStatusChange={setReviewStatus}
          onGroundingStatusChange={setGroundingStatus}
          onChooseItem={chooseItem}
        />
      ) : null}
      {activeTab === "paper" ? (
        <PaperMetadataReview
          papers={papers}
          selectedItem={selectedItem?.item_type === "paper" ? selectedItem : null}
          onSaved={() => completeAction("Paper metadata review saved.")}
          onError={failAction}
          onSelectPaper={onSelectPaper}
        />
      ) : null}
      {activeTab === "artifacts" ? (
        <GeneratedArtifactReview
          item={firstItemOfType(selectedItem, queue, "paper_artifact")}
          onSaved={() => completeAction("Artifact review saved.")}
          onError={failAction}
        />
      ) : null}
      {activeTab === "answers" ? (
        <AskAnswerReview
          item={firstItemOfType(selectedItem, queue, "rag_answer")}
          onSaved={() => completeAction("Ask answer review saved.")}
          onError={failAction}
        />
      ) : null}
      {activeTab === "recommendations" ? (
        <ThesisRecommendationReview
          item={firstItemOfType(selectedItem, queue, "thesis_recommendation")}
          onSaved={() => completeAction("Thesis recommendation review saved.")}
          onError={failAction}
        />
      ) : null}
      {activeTab === "events" ? <ReviewEventsPanel events={events} /> : null}
      </div>
    </section>
  );
}

function AdminOverviewPanel({ overview, loading }: { overview: AdminOverview | null; loading: boolean }) {
  if (loading && !overview) {
    return (
      <>
        <MetricSkeletonGrid count={8} />
        <div className="admin-grid">
          <ListSkeleton count={2} lines={2} />
          <ListSkeleton count={2} lines={2} />
        </div>
      </>
    );
  }
  if (!overview) {
    return <EmptyState title="Admin overview is not available yet" body="Start the backend and refresh this local demo page." />;
  }
  return (
    <>
      <div className="metrics-grid admin-metrics">
        <Metric label="Papers needing review" value={overview.papers_needing_metadata_review} />
        <Metric label="Missing PDFs" value={overview.papers_missing_pdfs} />
        <Metric label="Extraction failures" value={overview.papers_with_extraction_failures + overview.possible_scanned_pdfs} />
        <Metric label="Artifacts needing review" value={overview.artifacts_needing_review} />
        <Metric label="Ask answers needing review" value={overview.rag_answers.needs_review ?? 0} />
        <Metric label="Recommendations needing review" value={overview.thesis_recommendations.needs_review ?? 0} />
        <Metric label="Review events" value={overview.total_review_events} />
        <Metric label="Chunks" value={overview.total_chunks} />
      </div>

      <div className="admin-grid">
        <StatusBreakdown title="RAG answers" values={overview.rag_answers_by_grounding} />
        <StatusBreakdown title="Thesis recommendations" values={overview.thesis_recommendations_by_grounding} />
        <StatusBreakdown title="Paper artifacts" values={overview.paper_artifacts_by_grounding} />
        <StatusBreakdown title="Artifacts by type" values={overview.paper_artifacts_by_type} />
      </div>
    </>
  );
}

function ReviewQueuePanel({
  queue,
  total,
  itemType,
  reviewStatus,
  groundingStatus,
  loading,
  onItemTypeChange,
  onReviewStatusChange,
  onGroundingStatusChange,
  onChooseItem,
}: {
  queue: ReviewQueueItem[];
  total: number;
  itemType: string;
  reviewStatus: string;
  groundingStatus: string;
  loading: boolean;
  onItemTypeChange: (value: string) => void;
  onReviewStatusChange: (value: string) => void;
  onGroundingStatusChange: (value: string) => void;
  onChooseItem: (item: ReviewQueueItem) => void;
}) {
  return (
    <>
      <div className="admin-filter-row">
        <label>
          <span>Item type</span>
          <select value={itemType} onChange={(event) => onItemTypeChange(event.target.value)}>
            <option value="">All</option>
            <option value="paper">Paper</option>
            <option value="paper_artifact">Paper artifact</option>
            <option value="rag_answer">Ask answer</option>
            <option value="thesis_recommendation">Thesis recommendation</option>
          </select>
        </label>
        <label>
          <span>Review status</span>
          <select value={reviewStatus} onChange={(event) => onReviewStatusChange(event.target.value)}>
            <option value="">All</option>
            {REVIEW_STATUSES.map((status) => (
              <option key={status} value={status}>
                {status.replaceAll("_", " ")}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Grounding</span>
          <select value={groundingStatus} onChange={(event) => onGroundingStatusChange(event.target.value)}>
            <option value="">All</option>
            <option value="grounded">Grounded</option>
            <option value="partial">Partial</option>
            <option value="unsupported">Unsupported</option>
          </select>
        </label>
      </div>

      <div className="section-heading">
        <h2>Review Queue</h2>
        <span className="queue-count">{total} items</span>
      </div>
      <div className="paper-list">
        {loading && !queue.length ? <ListSkeleton count={4} lines={2} /> : null}
        {queue.map((item) => (
          <article className="review-row" key={`${item.item_type}-${item.item_id}`}>
            <div>
              <div className="paper-card__meta">
                <span>{item.item_type.replaceAll("_", " ")}</span>
                <span>{item.created_at ? formatDate(item.created_at) : "Date unknown"}</span>
              </div>
              <h3>{item.title}</h3>
              {item.warnings.length ? <p>{item.warnings.join(" ")}</p> : <p>No warnings recorded.</p>}
            </div>
            <div className="paper-card__badges">
              <StatusBadge label={item.status} />
              {item.grounding_status ? (
                <StatusBadge label={item.grounding_status} />
              ) : null}
              <button className="action-button" onClick={() => onChooseItem(item)}>
                Open
              </button>
            </div>
          </article>
        ))}
        {!loading && !queue.length ? <EmptyState title="No items match this review queue filter" body="Change the item type, status, or grounding filter to broaden the queue." /> : null}
      </div>
    </>
  );
}

function PaperMetadataReview({
  papers,
  selectedItem,
  onSaved,
  onError,
  onSelectPaper,
}: {
  papers: Paper[];
  selectedItem: ReviewQueueItem | null;
  onSaved: () => void;
  onError: (err: unknown) => void;
  onSelectPaper: (paperId: string) => void;
}) {
  const initialPaperId = selectedItem?.item_id ?? papers[0]?.paper_id ?? "";
  const [paperId, setPaperId] = useState(initialPaperId);
  const paper = useMemo(() => papers.find((item) => item.paper_id === paperId), [paperId, papers]);
  const selectedDetails = selectedItem?.item_id === paperId ? selectedItem.details : {};
  const [form, setForm] = useState(() => paperFormFrom(paper, selectedDetails));
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (selectedItem?.item_id && selectedItem.item_id !== paperId) {
      setPaperId(selectedItem.item_id);
    }
  }, [paperId, selectedItem]);

  useEffect(() => {
    const activePaper = papers.find((item) => item.paper_id === paperId);
    setForm(paperFormFrom(activePaper, selectedItem?.item_id === paperId ? selectedItem.details : {}));
  }, [paperId, papers, selectedItem]);

  if (!paper && !selectedItem) {
    return <EmptyState title="No paper is available for metadata review" body="Import seed data before using metadata review." />;
  }

  function updateField(field: string, value: string) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  function save() {
    if (!paperId) {
      return;
    }
    setSaving(true);
    patchAdminPaper(paperId, {
      title: form.title,
      authors: splitCsv(form.authors),
      year: form.year.trim() ? Number(form.year) : null,
      publication_date_raw: form.publication_date_raw || null,
      venue: form.venue || null,
      topics: splitCsv(form.topics),
      source_url: form.source_url || null,
      pdf_url: form.pdf_url || null,
      abstract: form.abstract || null,
      review_status: form.review_status as ReviewStatus,
      reviewer_notes: form.reviewer_notes || null,
    })
      .then(onSaved)
      .catch(onError)
      .finally(() => setSaving(false));
  }

  return (
    <article className="admin-card">
      <div className="section-heading section-heading--compact">
        <h2>Paper Metadata Review</h2>
        <button className="link-button" onClick={() => paperId && onSelectPaper(paperId)}>
          Open paper detail
        </button>
      </div>
      <label className="admin-field">
        <span>Paper</span>
        <select value={paperId} onChange={(event) => setPaperId(event.target.value)}>
          {papers.map((item) => (
            <option key={item.paper_id} value={item.paper_id}>
              {item.title}
            </option>
          ))}
        </select>
      </label>
      <div className="admin-form-grid">
        <TextField label="Title" value={form.title} onChange={(value) => updateField("title", value)} />
        <TextField label="Authors" value={form.authors} onChange={(value) => updateField("authors", value)} />
        <TextField label="Year" value={form.year} onChange={(value) => updateField("year", value)} />
        <TextField label="Publication date" value={form.publication_date_raw} onChange={(value) => updateField("publication_date_raw", value)} />
        <TextField label="Venue" value={form.venue} onChange={(value) => updateField("venue", value)} />
        <TextField label="Topics" value={form.topics} onChange={(value) => updateField("topics", value)} />
        <TextField label="Source URL" value={form.source_url} onChange={(value) => updateField("source_url", value)} />
        <TextField label="PDF URL" value={form.pdf_url} onChange={(value) => updateField("pdf_url", value)} />
      </div>
      <label className="admin-field">
        <span>Abstract</span>
        <textarea value={form.abstract} onChange={(event) => updateField("abstract", event.target.value)} rows={4} />
      </label>
      <div className="admin-form-grid admin-form-grid--small">
        <label className="admin-field">
          <span>Review status</span>
          <select value={form.review_status} onChange={(event) => updateField("review_status", event.target.value)}>
            {REVIEW_STATUSES.map((status) => (
              <option key={status} value={status}>
                {status.replaceAll("_", " ")}
              </option>
            ))}
          </select>
        </label>
        <TextField label="Reviewer notes" value={form.reviewer_notes} onChange={(value) => updateField("reviewer_notes", value)} />
      </div>
      <BusyButton busy={saving} busyLabel="Saving..." onClick={save}>
        Save Metadata Review
      </BusyButton>
    </article>
  );
}

function GeneratedArtifactReview({ item, onSaved, onError }: { item: ReviewQueueItem | null; onSaved: () => void; onError: (err: unknown) => void }) {
  const [notes, setNotes] = useState("");
  const [correctedText, setCorrectedText] = useState("");

  useEffect(() => {
    setNotes(getString(item?.details, "reviewer_notes"));
    setCorrectedText(getString(item?.details, "corrected_text"));
  }, [item]);

  if (!item) {
    return <EmptyState title="No paper artifact selected" body="Open an artifact from the review queue to inspect generated content and citations." />;
  }
  const activeItem = item;

  function save(status: ReviewStatus) {
    return reviewArtifact(activeItem.item_id, {
      review_status: status,
      reviewer_notes: notes,
      corrected_text: correctedText || undefined,
    }).then(onSaved);
  }

  return (
    <ReviewCard
      title={activeItem.title}
      status={activeItem.status}
      groundingStatus={activeItem.grounding_status}
      warnings={activeItem.warnings}
      onSave={save}
      onError={onError}
      notes={notes}
      onNotesChange={setNotes}
    >
      <p>{getString(activeItem.details, "generated_text") || "Generated text is stored as structured JSON for this artifact."}</p>
      <label className="admin-field">
        <span>Corrected text</span>
        <textarea value={correctedText} onChange={(event) => setCorrectedText(event.target.value)} rows={5} />
      </label>
      <StructuredPreview value={activeItem.details.generated_json} />
      <CitationPreview details={activeItem.details} />
    </ReviewCard>
  );
}

function AskAnswerReview({ item, onSaved, onError }: { item: ReviewQueueItem | null; onSaved: () => void; onError: (err: unknown) => void }) {
  const [notes, setNotes] = useState("");
  const [citationCorrect, setCitationCorrect] = useState("");
  const [faithfulness, setFaithfulness] = useState("");
  const [usefulness, setUsefulness] = useState("");

  useEffect(() => {
    setNotes(getString(item?.details, "reviewer_notes"));
    setCitationCorrect(boolToSelect(getBoolean(item?.details, "citation_correct")));
    setFaithfulness(numberToString(getNumber(item?.details, "answer_faithfulness_score")));
    setUsefulness(numberToString(getNumber(item?.details, "usefulness_score")));
  }, [item]);

  if (!item) {
    return <EmptyState title="No Ask TTLAB answer selected" body="Open an answer from the review queue to check faithfulness, usefulness, and citations." />;
  }
  const activeItem = item;

  function save(status: ReviewStatus) {
    return reviewAnswer(activeItem.item_id, {
      review_status: status,
      reviewer_notes: notes,
      citation_correct: selectToBool(citationCorrect),
      answer_faithfulness_score: faithfulness ? Number(faithfulness) : null,
      usefulness_score: usefulness ? Number(usefulness) : null,
    }).then(onSaved);
  }

  return (
    <ReviewCard
      title={getString(activeItem.details, "question") || activeItem.title}
      status={activeItem.status}
      groundingStatus={activeItem.grounding_status}
      warnings={activeItem.warnings}
      onSave={save}
      onError={onError}
      notes={notes}
      onNotesChange={setNotes}
    >
      <p>{getString(activeItem.details, "answer")}</p>
      <div className="admin-form-grid admin-form-grid--small">
        <label className="admin-field">
          <span>Citations correct?</span>
          <select value={citationCorrect} onChange={(event) => setCitationCorrect(event.target.value)}>
            <option value="">Not checked</option>
            <option value="true">Yes</option>
            <option value="false">No</option>
          </select>
        </label>
        <ScoreSelect label="Faithfulness" value={faithfulness} onChange={setFaithfulness} />
        <ScoreSelect label="Usefulness" value={usefulness} onChange={setUsefulness} />
      </div>
      <CitationPreview details={activeItem.details} />
    </ReviewCard>
  );
}

function ThesisRecommendationReview({ item, onSaved, onError }: { item: ReviewQueueItem | null; onSaved: () => void; onError: (err: unknown) => void }) {
  const [notes, setNotes] = useState("");

  useEffect(() => {
    setNotes(getString(item?.details, "reviewer_notes"));
  }, [item]);

  if (!item) {
    return <EmptyState title="No thesis recommendation selected" body="Open a recommendation run from the review queue to inspect suggestions and citations." />;
  }
  const activeItem = item;

  function save(status: ReviewStatus) {
    return reviewRecommendation(activeItem.item_id, {
      review_status: status,
      reviewer_notes: notes,
    }).then(onSaved);
  }

  const recommendations = getArray(activeItem.details, "recommendations");
  return (
    <ReviewCard
      title={activeItem.title}
      status={activeItem.status}
      groundingStatus={activeItem.grounding_status}
      warnings={activeItem.warnings}
      onSave={save}
      onError={onError}
      notes={notes}
      onNotesChange={setNotes}
    >
      <StructuredPreview value={activeItem.details.request} title="Student request" />
      <div className="paper-list">
        {recommendations.map((value, index) => {
          const recommendation = asRecord(value);
          return (
            <article className="citation-card" key={`${activeItem.item_id}-${index}`}>
              <h3>{getString(recommendation, "extension_title") || getString(recommendation, "paper_title") || `Recommendation ${index + 1}`}</h3>
              <p>{getString(recommendation, "why_it_fits_student")}</p>
              <p>{getString(recommendation, "extension_summary")}</p>
              <CitationPreview details={recommendation} />
            </article>
          );
        })}
      </div>
    </ReviewCard>
  );
}

function ReviewEventsPanel({ events }: { events: ReviewEvent[] }) {
  return (
    <div className="paper-list">
      {events.map((event) => (
        <article className="review-row" key={event.review_event_id}>
          <div>
            <div className="paper-card__meta">
              <span>{formatDate(event.created_at)}</span>
              <span>{event.item_type.replaceAll("_", " ")}</span>
              <span>{event.action.replaceAll("_", " ")}</span>
              <span>{event.reviewer_name}{event.reviewer_type ? ` · ${event.reviewer_type}` : ""}{event.reviewer_role ? ` · ${event.reviewer_role}` : ""}</span>
              {event.request_id ? <span>Request {event.request_id}</span> : null}
            </div>
            <h3>{event.item_id}</h3>
            <p>{event.reviewer_notes || "No notes recorded."}</p>
          </div>
          <div className="paper-card__badges">
            <StatusBadge label={event.previous_status ?? "none"} />
            <StatusBadge label={event.new_status ?? "none"} tone={event.new_status === "approved" ? "good" : "warn"} />
          </div>
        </article>
      ))}
      {!events.length ? <EmptyState title="No review events yet" body="Approve, reject, correct, or mark an item to start the local audit trail." /> : null}
    </div>
  );
}

function ReviewCard({
  title,
  status,
  groundingStatus,
  warnings,
  notes,
  onNotesChange,
  onSave,
  onError,
  children,
}: {
  title: string;
  status: string;
  groundingStatus: string | null;
  warnings: string[];
  notes: string;
  onNotesChange: (value: string) => void;
  onSave: (status: ReviewStatus) => Promise<unknown> | void;
  onError: (err: unknown) => void;
  children: ReactNode;
}) {
  const [savingStatus, setSavingStatus] = useState<ReviewStatus | null>(null);

  function save(status: ReviewStatus) {
    setSavingStatus(status);
    Promise.resolve(onSave(status))
      .catch(onError)
      .finally(() => setSavingStatus(null));
  }

  return (
    <article className="admin-card">
      <div className="paper-card__badges paper-card__badges--left">
        <StatusBadge label={status} />
        {groundingStatus ? <StatusBadge label={groundingStatus} /> : null}
      </div>
      <h2>{title}</h2>
      {warnings.length ? <p className="notice notice--warning">{warnings.join(" ")}</p> : null}
      {children}
      <label className="admin-field">
        <span>Reviewer notes</span>
        <textarea value={notes} onChange={(event) => onNotesChange(event.target.value)} rows={4} />
      </label>
      <div className="admin-action-row">
        <BusyButton busy={savingStatus === "approved"} busyLabel="Approving..." onClick={() => save("approved")}>
          Approve
        </BusyButton>
        <BusyButton variant="secondary" busy={savingStatus === "needs_review"} busyLabel="Marking..." onClick={() => save("needs_review")}>
          Needs Review
        </BusyButton>
        <BusyButton variant="danger" busy={savingStatus === "rejected"} busyLabel="Rejecting..." onClick={() => save("rejected")}>
          Reject
        </BusyButton>
      </div>
    </article>
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

function StatusBreakdown({ title, values }: { title: string; values: Record<string, number> }) {
  return (
    <article className="admin-card">
      <h3>{title}</h3>
      <div className="status-table">
        {Object.entries(values).map(([key, value]) => (
          <p key={key}>
            <span>{key.replaceAll("_", " ")}</span>
            <strong>{value}</strong>
          </p>
        ))}
      </div>
    </article>
  );
}

function TextField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="admin-field">
      <span>{label}</span>
      <input value={value} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

function ScoreSelect({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="admin-field">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">Not scored</option>
        {[1, 2, 3, 4, 5].map((score) => (
          <option key={score} value={score}>
            {score}
          </option>
        ))}
      </select>
    </label>
  );
}

function CitationPreview({ details }: { details: Record<string, unknown> }) {
  const citations = getArray(details, "citations").map(asRecord).filter((item) => getString(item, "chunk_id"));
  if (!citations.length) {
    return <EmptyState title="No citations recorded" body="This item should be reviewed carefully before approval." />;
  }
  return (
    <details className="retrieved-details" open>
      <summary>Citations</summary>
      <div className="paper-list">
        {citations.map((citation) => (
          <article className="citation-card" key={getString(citation, "chunk_id")}>
            <div className="paper-card__meta">
              <span>{getString(citation, "section") || "Unknown section"}</span>
              <span>
                Pages {getStringOrNumber(citation, "page_start") || "?"}-{getStringOrNumber(citation, "page_end") || "?"}
              </span>
            </div>
            <h3>{getString(citation, "title") || getString(citation, "paper_id")}</h3>
            <p>{getString(citation, "snippet")}</p>
          </article>
        ))}
      </div>
    </details>
  );
}

function StructuredPreview({ value, title = "Structured JSON" }: { value: unknown; title?: string }) {
  if (value === null || value === undefined) {
    return null;
  }
  return (
    <details className="retrieved-details">
      <summary>{title}</summary>
      <pre className="json-preview">{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}

function paperFormFrom(paper: Paper | undefined, details: Record<string, unknown>) {
  return {
    title: getString(details, "title") || paper?.title || "",
    authors: getStringArray(details, "authors").join(", ") || paper?.authors.join(", ") || "",
    year: numberToString(getNumber(details, "year") ?? paper?.year ?? null),
    publication_date_raw: getString(details, "publication_date_raw") || paper?.publication_date_raw || "",
    venue: getString(details, "venue") || paper?.venue || "",
    topics: getStringArray(details, "topics").join(", ") || paper?.topics.join(", ") || "",
    source_url: getString(details, "source_url") || paper?.source_url || "",
    pdf_url: getString(details, "pdf_url") || paper?.pdf_url || "",
    abstract: getString(details, "abstract") || paper?.abstract || "",
    review_status: getString(details, "review_status") || paper?.review_status || "needs_review",
    reviewer_notes: getString(details, "reviewer_notes") || paper?.reviewer_notes || "",
  };
}

function firstItemOfType(
  selectedItem: ReviewQueueItem | null,
  queue: ReviewQueueItem[],
  itemType: ReviewQueueItem["item_type"],
): ReviewQueueItem | null {
  if (selectedItem?.item_type === itemType) {
    return selectedItem;
  }
  return queue.find((item) => item.item_type === itemType) ?? null;
}

function tabForItem(itemType: ReviewQueueItem["item_type"]): AdminTab {
  if (itemType === "paper") {
    return "paper";
  }
  if (itemType === "paper_artifact") {
    return "artifacts";
  }
  if (itemType === "rag_answer") {
    return "answers";
  }
  return "recommendations";
}

function splitCsv(value: string): string[] {
  return value
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function getString(record: Record<string, unknown> | undefined, key: string): string {
  if (!record) {
    return "";
  }
  const value = record[key];
  return typeof value === "string" ? value : "";
}

function getStringArray(record: Record<string, unknown> | undefined, key: string): string[] {
  if (!record) {
    return [];
  }
  const value = record[key];
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function getArray(record: Record<string, unknown> | undefined, key: string): unknown[] {
  if (!record) {
    return [];
  }
  const value = record[key];
  return Array.isArray(value) ? value : [];
}

function getNumber(record: Record<string, unknown> | undefined, key: string): number | null {
  if (!record) {
    return null;
  }
  const value = record[key];
  return typeof value === "number" ? value : null;
}

function getBoolean(record: Record<string, unknown> | undefined, key: string): boolean | null {
  if (!record) {
    return null;
  }
  const value = record[key];
  return typeof value === "boolean" ? value : null;
}

function getStringOrNumber(record: Record<string, unknown>, key: string): string {
  const value = record[key];
  if (typeof value === "number") {
    return String(value);
  }
  return typeof value === "string" ? value : "";
}

function boolToSelect(value: boolean | null): string {
  if (value === null) {
    return "";
  }
  return value ? "true" : "false";
}

function selectToBool(value: string): boolean | null {
  if (value === "true") {
    return true;
  }
  if (value === "false") {
    return false;
  }
  return null;
}

function numberToString(value: number | null | undefined): string {
  return value === null || value === undefined ? "" : String(value);
}

function formatDate(value: string): string {
  return new Date(value).toLocaleString();
}
