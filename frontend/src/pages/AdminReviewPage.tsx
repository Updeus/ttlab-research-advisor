import { useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";

import {
  fetchAdminOverview,
  fetchAdminPublicationPreview,
  fetchActorCapabilities,
  fetchIngestionSyncStatus,
  fetchReviewEvents,
  fetchReviewQueue,
  decidePaperPublication,
  patchAdminPaper,
  reviewAnswer,
  reviewArtifact,
  reviewRecommendation,
  reviewGraphRecord,
  requestIngestionSync,
  reviewExtraction,
  saveArtifactCorrection,
  saveGraphCorrection,
  saveRecommendationCorrection,
} from "../api/client";
import type { GraphReviewItemType } from "../api/client";
import { StatusBadge } from "../components/StatusBadge";
import { BusyButton, EmptyState, ListSkeleton, MetricSkeletonGrid } from "../components/UiPrimitives";
import type { ToastTone } from "../components/UiPrimitives";
import type { ActorCapabilities, AdminOverview, AdminPublicationPreview, AdminPublicationPreviewPaper, IngestionSyncStatus, Paper, ReviewEvent, ReviewQueueItem, ReviewStatus } from "../types/paper";

type AdminTab = "overview" | "queue" | "publication" | "paper" | "extraction" | "identities" | "topics" | "artifacts" | "answers" | "recommendations" | "events";

type AdminReviewPageProps = {
  papers: Paper[];
  onSelectPaper: (paperId: string) => void;
  onNotify?: (message: string, tone?: ToastTone) => void;
  onDataChanged?: () => void;
};

const ADMIN_TABS: { id: AdminTab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "queue", label: "Review Queue" },
  { id: "publication", label: "Publication Preview" },
  { id: "paper", label: "Paper Metadata" },
  { id: "extraction", label: "Extraction Review" },
  { id: "identities", label: "Author Identities" },
  { id: "topics", label: "Topics & Links" },
  { id: "artifacts", label: "Artifacts" },
  { id: "answers", label: "Ask Answers" },
  { id: "recommendations", label: "Recommendations" },
  { id: "events", label: "Review Events" },
];

const REVIEW_STATUSES: ReviewStatus[] = ["needs_review", "ai_reviewed", "reviewed", "approved", "rejected", "needs_reprocess"];
const REVIEW_QUEUE_PAGE_SIZE = 50;
const REVIEW_EVENT_PAGE_SIZE = 50;
const GRAPH_GROUP_TYPES: Record<"identities" | "topics", GraphReviewItemType[]> = {
  identities: ["author", "author_alias"],
  topics: ["topic", "paper_topic", "author_topic"],
};

type GraphGovernanceForm = {
  canonical_name: string;
  affiliation: string;
  email: string;
  profile_url: string;
  persistent_identifier: string;
  persistent_identifier_source: string;
  identity_status: string;
  merged_into_author_id: string;
  alias: string;
  canonical_author_id: string;
  name: string;
  description: string;
  score: string;
  paper_count: string;
  evidence_json: string;
};

export function AdminReviewPage({ papers, onSelectPaper, onNotify, onDataChanged }: AdminReviewPageProps) {
  const [activeTab, setActiveTab] = useState<AdminTab>("overview");
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [publicationPreview, setPublicationPreview] = useState<AdminPublicationPreview | null>(null);
  const [actorCapabilities, setActorCapabilities] = useState<ActorCapabilities | null>(null);
  const [syncStatus, setSyncStatus] = useState<IngestionSyncStatus | null>(null);
  const [requestingSync, setRequestingSync] = useState(false);
  const [queue, setQueue] = useState<ReviewQueueItem[]>([]);
  const [queueTotal, setQueueTotal] = useState(0);
  const [queueOffset, setQueueOffset] = useState(0);
  const [events, setEvents] = useState<ReviewEvent[]>([]);
  const [eventTotal, setEventTotal] = useState(0);
  const [eventOffset, setEventOffset] = useState(0);
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
      fetchAdminPublicationPreview(),
      fetchActorCapabilities(),
      fetchIngestionSyncStatus(),
      fetchReviewQueue({
        item_type: itemType || undefined,
        review_status: reviewStatus || undefined,
        grounding_status: groundingStatus || undefined,
        limit: REVIEW_QUEUE_PAGE_SIZE,
        offset: queueOffset,
      }),
      fetchReviewEvents({ limit: REVIEW_EVENT_PAGE_SIZE, offset: eventOffset }),
    ])
      .then(([overviewData, previewData, capabilitiesData, syncData, queueData, eventData]) => {
        setOverview(overviewData);
        setPublicationPreview(previewData);
        setActorCapabilities(capabilitiesData);
        setSyncStatus(syncData);
        setQueue(queueData.items);
        setQueueTotal(queueData.total);
        setEvents(eventData.items);
        setEventTotal(eventData.total);
        setSelectedItem((current) => {
          if (!current) return queueData.items[0] ?? null;
          return queueData.items.find(
            (item) => item.item_type === current.item_type && item.item_id === current.item_id,
          ) ?? null;
        });
        if (queueData.total === 0 && queueOffset !== 0) setQueueOffset(0);
        else if (queueOffset >= queueData.total && queueData.total > 0) {
          setQueueOffset(Math.floor((queueData.total - 1) / REVIEW_QUEUE_PAGE_SIZE) * REVIEW_QUEUE_PAGE_SIZE);
        }
        if (eventData.total === 0 && eventOffset !== 0) setEventOffset(0);
        else if (eventOffset >= eventData.total && eventData.total > 0) {
          setEventOffset(Math.floor((eventData.total - 1) / REVIEW_EVENT_PAGE_SIZE) * REVIEW_EVENT_PAGE_SIZE);
        }
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Unable to load admin review data."))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    refresh();
    // Filters intentionally trigger a fresh queue; refresh is small and local.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [itemType, reviewStatus, groundingStatus, queueOffset, eventOffset]);

  function chooseItem(item: ReviewQueueItem) {
    setSelectedItem(item);
    const tab = tabForItem(item.item_type);
    if (isGraphQueueItem(item)) {
      setQueueOffset(0);
      setItemType(item.item_type);
    }
    setActiveTab(tab);
  }

  function activateTab(tab: AdminTab) {
    if (tab === "identities" && !GRAPH_GROUP_TYPES.identities.includes(itemType as GraphReviewItemType)) {
      setQueueOffset(0);
      setItemType("author");
    }
    if (tab === "topics" && !GRAPH_GROUP_TYPES.topics.includes(itemType as GraphReviewItemType)) {
      setQueueOffset(0);
      setItemType("topic");
    }
    setActiveTab(tab);
  }

  function completeAction(text: string) {
    onNotify?.(text, "success");
    onDataChanged?.();
    refresh();
  }

  function failAction(err: unknown) {
    const text = err instanceof Error ? err.message : "Admin review action failed.";
    setError(text);
    onNotify?.(text, "error");
  }

  function queueIngestionSync() {
    setRequestingSync(true);
    requestIngestionSync()
      .then((response) => {
        setSyncStatus(response.sync);
        onNotify?.(response.message, response.accepted ? "success" : "warning");
        if (response.accepted) {
          onDataChanged?.();
        }
      })
      .catch(failAction)
      .finally(() => setRequestingSync(false));
  }

  function handleTabKey(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    let next = index;
    if (event.key === "ArrowRight") next = (index + 1) % ADMIN_TABS.length;
    else if (event.key === "ArrowLeft") next = (index - 1 + ADMIN_TABS.length) % ADMIN_TABS.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = ADMIN_TABS.length - 1;
    else return;
    event.preventDefault();
    activateTab(ADMIN_TABS[next].id);
    tabRefs.current[next]?.focus();
  }

  return (
    <section className="page-section" aria-labelledby="admin-review-title">
      <h2 id="admin-review-title" className="sr-only">Admin review</h2>
      <p className="notice">Protected reviewer tools. Review actions are attributed by the authenticated actor and recorded as append-only audit events.</p>
      {actorCapabilities ? (
        <p className="notice" role="status">
          Acting as <strong>{actorCapabilities.actor.actor_id}</strong> ({actorCapabilities.actor.reviewer_type} {actorCapabilities.actor.role})
          {actorCapabilities.actor.local_demo_bypass ? " through the local demo bypass" : ""}.
          {actorCapabilities.capabilities.approve_or_reject
            ? " Approval and rejection are available for this actor."
            : " This actor cannot approve or reject; only permitted review-state actions are shown."}
        </p>
      ) : null}
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
            onClick={() => activateTab(tab.id)}
            onKeyDown={(event) => handleTabKey(event, index)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div role="tabpanel" id={`admin-panel-${activeTab}`} aria-labelledby={`admin-tab-${activeTab}`} tabIndex={0}>
      {activeTab === "overview" ? (
        <AdminOverviewPanel
          overview={overview}
          syncStatus={syncStatus}
          loading={loading}
          requestingSync={requestingSync}
          onRequestSync={queueIngestionSync}
          capabilities={actorCapabilities}
        />
      ) : null}
      {activeTab === "queue" ? (
        <ReviewQueuePanel
          queue={queue}
          total={queueTotal}
          itemType={itemType}
          reviewStatus={reviewStatus}
          groundingStatus={groundingStatus}
          loading={loading}
          onItemTypeChange={(value) => { setQueueOffset(0); setItemType(value); }}
          onReviewStatusChange={(value) => { setQueueOffset(0); setReviewStatus(value); }}
          onGroundingStatusChange={(value) => { setQueueOffset(0); setGroundingStatus(value); }}
          offset={queueOffset}
          pageSize={REVIEW_QUEUE_PAGE_SIZE}
          onOffsetChange={setQueueOffset}
          onChooseItem={chooseItem}
        />
      ) : null}
      {activeTab === "publication" ? (
        <PublicationPreviewPanel
          preview={publicationPreview}
          loading={loading}
          capabilities={actorCapabilities}
          onSaved={() => completeAction("Publication and rights decision saved.")}
          onError={failAction}
        />
      ) : null}
      {activeTab === "paper" ? (
        <PaperMetadataReview
          papers={papers}
          selectedItem={selectedItem?.item_type === "paper" ? selectedItem : null}
          onSaved={() => completeAction("Paper metadata review saved.")}
          onError={failAction}
          onSelectPaper={onSelectPaper}
          capabilities={actorCapabilities}
        />
      ) : null}
      {activeTab === "extraction" ? (
        <ExtractionReview
          preview={publicationPreview}
          selectedItem={selectedItem?.item_type === "paper" ? selectedItem : null}
          capabilities={actorCapabilities}
          onSaved={() => completeAction("Extraction review saved.")}
          onError={failAction}
        />
      ) : null}
      {activeTab === "identities" ? (
        <GraphGovernanceReview
          group="identities"
          items={queue}
          selectedItem={isGraphQueueItem(selectedItem) ? selectedItem : null}
          itemTypeFilter={itemType}
          total={queueTotal}
          offset={queueOffset}
          pageSize={REVIEW_QUEUE_PAGE_SIZE}
          onItemTypeChange={(value) => { setQueueOffset(0); setItemType(value); }}
          onOffsetChange={setQueueOffset}
          capabilities={actorCapabilities}
          onSaved={() => completeAction("Author identity or alias review saved.")}
          onError={failAction}
        />
      ) : null}
      {activeTab === "topics" ? (
        <GraphGovernanceReview
          group="topics"
          items={queue}
          selectedItem={isGraphQueueItem(selectedItem) ? selectedItem : null}
          itemTypeFilter={itemType}
          total={queueTotal}
          offset={queueOffset}
          pageSize={REVIEW_QUEUE_PAGE_SIZE}
          onItemTypeChange={(value) => { setQueueOffset(0); setItemType(value); }}
          onOffsetChange={setQueueOffset}
          capabilities={actorCapabilities}
          onSaved={() => completeAction("Topic or evidence-link review saved.")}
          onError={failAction}
        />
      ) : null}
      {activeTab === "artifacts" ? (
        <GeneratedArtifactReview
          item={firstItemOfType(selectedItem, queue, "paper_artifact")}
          capabilities={actorCapabilities}
          onSaved={() => completeAction("Artifact review saved.")}
          onError={failAction}
        />
      ) : null}
      {activeTab === "answers" ? (
        <AskAnswerReview
          item={firstItemOfType(selectedItem, queue, "rag_answer")}
          capabilities={actorCapabilities}
          onSaved={() => completeAction("Ask answer review saved.")}
          onError={failAction}
        />
      ) : null}
      {activeTab === "recommendations" ? (
        <ThesisRecommendationReview
          item={firstItemOfType(selectedItem, queue, "thesis_recommendation")}
          capabilities={actorCapabilities}
          onSaved={() => completeAction("Thesis recommendation review saved.")}
          onError={failAction}
        />
      ) : null}
      {activeTab === "events" ? (
        <ReviewEventsPanel
          events={events}
          total={eventTotal}
          offset={eventOffset}
          pageSize={REVIEW_EVENT_PAGE_SIZE}
          onOffsetChange={setEventOffset}
        />
      ) : null}
      </div>
    </section>
  );
}

function PublicationPreviewPanel({
  preview,
  loading,
  capabilities,
  onSaved,
  onError,
}: {
  preview: AdminPublicationPreview | null;
  loading: boolean;
  capabilities: ActorCapabilities | null;
  onSaved: () => void;
  onError: (err: unknown) => void;
}) {
  if (loading && !preview) return <ListSkeleton count={3} lines={3} />;
  if (!preview) {
    return <EmptyState title="Local review preview unavailable" body="The protected publication-preview endpoint did not return a reviewer view." />;
  }
  return (
    <section aria-labelledby="publication-preview-title">
      <div className="section-heading section-heading--compact">
        <div>
          <p className="eyebrow">Local reviewer surface · not public</p>
          <h2 id="publication-preview-title">Publication Preview</h2>
        </div>
        <StatusBadge label={`${preview.items.length} review records`} tone="warn" />
      </div>
      <p className="notice notice--warning" role="status">{preview.notice}</p>
      <p>This protected view may include records that are hidden from the public catalogue. It is never used as a fallback for public Papers, Search, Ask, Finder, or Explorer routes.</p>
      <div className="paper-list">
        {preview.items.map((paper) => (
          <PublicationDecisionCard
            key={paper.paper_id}
            paper={paper}
            canDecide={Boolean(capabilities?.capabilities.set_publication_and_rights)}
            onSaved={onSaved}
            onError={onError}
          />
        ))}
        {!preview.items.length ? (
          <EmptyState title="No local records are awaiting publication review" body="The reviewer preview is empty; this does not change the fail-closed public catalogue policy." />
        ) : null}
      </div>
    </section>
  );
}

function PublicationDecisionCard({
  paper,
  canDecide,
  onSaved,
  onError,
}: {
  paper: AdminPublicationPreviewPaper;
  canDecide: boolean;
  onSaved: () => void;
  onError: (err: unknown) => void;
}) {
  const [publicationStatus, setPublicationStatus] = useState(paper.publication_status);
  const [rightsStatus, setRightsStatus] = useState(paper.rights_status);
  const [publicAccessLevel, setPublicAccessLevel] = useState(paper.public_access_level);
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setPublicationStatus(paper.publication_status);
    setRightsStatus(paper.rights_status);
    setPublicAccessLevel(paper.public_access_level);
    setNotes("");
  }, [paper]);

  function save() {
    setSaving(true);
    decidePaperPublication(paper.paper_id, {
      publication_status: publicationStatus as "pending_review" | "published" | "hidden",
      rights_status: rightsStatus as "unknown" | "cleared" | "restricted",
      public_access_level: publicAccessLevel as "hidden" | "metadata_only" | "searchable",
      reviewer_notes: notes || undefined,
    })
      .then(onSaved)
      .catch(onError)
      .finally(() => setSaving(false));
  }

  return (
    <article className="review-row">
      <div>
        <div className="paper-card__meta">
          <span>{paper.year ?? "Year needs review"}</span>
          <span>{paper.venue ?? "Venue needs review"}</span>
          <span>{paper.paper_id}</span>
        </div>
        <h3>{paper.title}</h3>
        <p>{paper.authors.join(", ") || "Authors need review"}</p>
        <div className="chip-row chip-row--compact">
          {paper.topics.map((topic) => <span key={topic}>{topic}</span>)}
        </div>
        {canDecide ? (
          <div className="admin-form-grid">
            <label className="admin-field">
              <span>Editorial publication status</span>
              <select value={publicationStatus} onChange={(event) => setPublicationStatus(event.target.value)}>
                <option value="pending_review">Pending review</option>
                <option value="published">Published</option>
                <option value="hidden">Hidden</option>
              </select>
            </label>
            <label className="admin-field">
              <span>PDF/content rights status</span>
              <select value={rightsStatus} onChange={(event) => setRightsStatus(event.target.value)}>
                <option value="unknown">Unknown</option>
                <option value="cleared">Cleared</option>
                <option value="restricted">Restricted</option>
              </select>
            </label>
            <label className="admin-field">
              <span>Public access level</span>
              <select value={publicAccessLevel} onChange={(event) => setPublicAccessLevel(event.target.value)}>
                <option value="hidden">Hidden</option>
                <option value="metadata_only">Metadata only</option>
                <option value="searchable">Searchable full text</option>
              </select>
            </label>
            <label className="admin-field">
              <span>Decision notes</span>
              <textarea value={notes} onChange={(event) => setNotes(event.target.value)} rows={3} />
            </label>
            <BusyButton busy={saving} busyLabel="Saving decision..." onClick={save}>
              Save publication decision
            </BusyButton>
          </div>
        ) : (
          <p className="field-help">Only an authenticated human administrator can record publication, rights, and public-access decisions.</p>
        )}
      </div>
      <div className="paper-card__badges">
        <StatusBadge label={`editorial: ${paper.publication_status}`} />
        <StatusBadge label={`rights: ${paper.rights_status}`} />
        <StatusBadge label={`public access: ${paper.public_access_level}`} />
        <StatusBadge label={`corpus: ${paper.corpus_eligibility_status}`} />
        <StatusBadge label={`extraction review: ${paper.extraction_review_status ?? "needs_review"}`} />
      </div>
    </article>
  );
}

function AdminOverviewPanel({
  overview,
  syncStatus,
  loading,
  requestingSync,
  onRequestSync,
  capabilities,
}: {
  overview: AdminOverview | null;
  syncStatus: IngestionSyncStatus | null;
  loading: boolean;
  requestingSync: boolean;
  onRequestSync: () => void;
  capabilities: ActorCapabilities | null;
}) {
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
      <article className="admin-card ingestion-sync-card" aria-labelledby="ingestion-sync-title">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Automated acquisition</p>
            <h2 id="ingestion-sync-title">TTLAB publication synchronization</h2>
          </div>
          <StatusBadge
            label={syncStatus?.running ? "running" : syncStatus?.enabled ? "scheduled" : "manual only"}
            tone={syncStatus?.running ? "warn" : syncStatus?.enabled ? "good" : "neutral"}
          />
        </div>
        {syncStatus ? (
          <div className="ingestion-sync-details">
            <p>
              {syncStatus.enabled
                ? `Daily schedule: ${syncStatus.schedule} (${syncStatus.timezone}).`
                : "Scheduled polling is disabled. The dedicated worker can still process a protected manual request."}
            </p>
            <dl className="detail-list detail-list--compact">
              <div><dt>Next scheduled run</dt><dd>{syncStatus.next_scheduled_at ? formatDate(syncStatus.next_scheduled_at) : "Not scheduled"}</dd></div>
              <div><dt>Last successful run</dt><dd>{syncStatus.last_success_at ? formatDate(syncStatus.last_success_at) : "No successful run yet"}</dd></div>
              <div><dt>Last result</dt><dd>{syncStatus.last_run?.status ?? "No runs recorded"}</dd></div>
              <div><dt>Manual request</dt><dd>{syncStatus.manual_request_pending ? "Queued" : "None pending"}</dd></div>
            </dl>
            {syncStatus.last_run?.error_message ? <p className="notice notice--error">{syncStatus.last_run.error_message}</p> : null}
          </div>
        ) : <p>Worker status is unavailable.</p>}
        <div>
          <BusyButton
            busy={requestingSync}
            busyLabel="Queueing..."
            onClick={onRequestSync}
            disabled={
              !capabilities?.capabilities.trigger_ingestion
              || Boolean(syncStatus?.manual_request_pending)
              || syncStatus?.manual_trigger_allowed === false
            }
          >
            {syncStatus?.manual_request_pending
              ? "Synchronization queued"
              : !capabilities
                ? "Checking actor permission..."
                : !capabilities.capabilities.trigger_ingestion || syncStatus?.manual_trigger_allowed === false
                ? "Admin role required"
                : "Request synchronization now"}
          </BusyButton>
        </div>
        <p className="field-help">The API records this request; the separately deployed ingestion worker performs the network and indexing work.</p>
      </article>

      <section
        className="admin-card admin-governance-summary"
        aria-labelledby="admin-governance-summary-title"
        data-admin-governance-capture="aggregate-summary"
      >
        <div className="section-heading section-heading--compact">
          <div>
            <p className="eyebrow">Aggregate governance workload</p>
            <h2 id="admin-governance-summary-title">Review queues at a glance</h2>
          </div>
          <StatusBadge label="protected" tone="neutral" />
        </div>
        {capabilities ? (
          <dl className="detail-list detail-list--compact">
            <div><dt>Actor ID</dt><dd>{capabilities.actor.actor_id}</dd></div>
            <div><dt>Reviewer type</dt><dd>{capabilities.actor.reviewer_type}</dd></div>
            <div><dt>Role</dt><dd>{capabilities.actor.role}</dd></div>
            <div><dt>Human approval</dt><dd>{capabilities.capabilities.approve_or_reject ? "permitted" : "not permitted"}</dd></div>
          </dl>
        ) : <p className="field-help">Actor permissions are still loading.</p>}
        <p className="field-help">These aggregate counts expose no record text. Rights decisions and ingestion remain unavailable unless the server explicitly grants those capabilities.</p>
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
      </section>

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
  offset,
  pageSize,
  onOffsetChange,
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
  offset: number;
  pageSize: number;
  onOffsetChange: (offset: number) => void;
}) {
  return (
    <>
      <div className="admin-filter-row">
        <label>
          <span>Item type</span>
          <select value={itemType} onChange={(event) => onItemTypeChange(event.target.value)}>
            <option value="">All</option>
            <option value="paper">Paper</option>
            <option value="author">Author identity</option>
            <option value="author_alias">Author alias</option>
            <option value="topic">Topic</option>
            <option value="paper_topic">Paper-topic evidence link</option>
            <option value="author_topic">Author-topic evidence link</option>
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
      <PaginationControls
        label="Review queue"
        total={total}
        offset={offset}
        pageSize={pageSize}
        onOffsetChange={onOffsetChange}
      />
    </>
  );
}

function PaperMetadataReview({
  papers,
  selectedItem,
  onSaved,
  onError,
  onSelectPaper,
  capabilities,
}: {
  papers: Paper[];
  selectedItem: ReviewQueueItem | null;
  onSaved: () => void;
  onError: (err: unknown) => void;
  onSelectPaper: (paperId: string) => void;
  capabilities: ActorCapabilities | null;
}) {
  const initialPaperId = selectedItem?.item_id ?? papers[0]?.paper_id ?? "";
  const [paperId, setPaperId] = useState(initialPaperId);
  const paper = useMemo(() => papers.find((item) => item.paper_id === paperId), [paperId, papers]);
  const selectedDetails = selectedItem?.item_id === paperId ? selectedItem.details : {};
  const currentReviewStatus = getString(selectedDetails, "review_status") || paper?.review_status || "needs_review";
  const permittedStatuses = allowedReviewTargets(currentReviewStatus, capabilities);
  const [form, setForm] = useState(() => paperFormFrom(paper, selectedDetails));
  const [saving, setSaving] = useState(false);
  const [yearError, setYearError] = useState<string | null>(null);

  useEffect(() => {
    if (selectedItem?.item_id && selectedItem.item_id !== paperId) {
      setPaperId(selectedItem.item_id);
    }
  }, [paperId, selectedItem]);

  useEffect(() => {
    const activePaper = papers.find((item) => item.paper_id === paperId);
    setForm(paperFormFrom(activePaper, selectedItem?.item_id === paperId ? selectedItem.details : {}));
    setYearError(null);
  }, [paperId, papers, selectedItem]);

  if (!paper && !selectedItem) {
    return <EmptyState title="No paper is available for metadata review" body="Import seed data before using metadata review." />;
  }

  function updateField(field: string, value: string) {
    setForm((current) => ({ ...current, [field]: value }));
    if (field === "year") setYearError(null);
  }

  function save() {
    if (!paperId) {
      return;
    }
    const parsedYear = parsePaperYear(form.year);
    if (parsedYear.error) {
      setYearError(parsedYear.error);
      return;
    }
    if (!permittedStatuses.includes(form.review_status as ReviewStatus)) {
      onError(new Error("Choose a review status permitted for the current actor and record state."));
      return;
    }
    setSaving(true);
    patchAdminPaper(paperId, {
      title: form.title,
      authors: splitCsv(form.authors),
      year: parsedYear.value,
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
        <button className="link-button" disabled={!paper} onClick={() => paperId && paper && onSelectPaper(paperId)}>
          Open paper detail
        </button>
      </div>
      <label className="admin-field">
        <span>Paper</span>
        <select value={paperId} onChange={(event) => setPaperId(event.target.value)}>
          {selectedItem && !papers.some((item) => item.paper_id === selectedItem.item_id) ? (
            <option value={selectedItem.item_id}>{getString(selectedItem.details, "title") || selectedItem.title} (protected review record)</option>
          ) : null}
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
        <label className="admin-field" htmlFor="paper-review-year">
          <span>Year</span>
          <input
            id="paper-review-year"
            type="number"
            inputMode="numeric"
            min={1800}
            max={2200}
            step={1}
            value={form.year}
            aria-invalid={Boolean(yearError)}
            aria-describedby={yearError ? "paper-review-year-error" : undefined}
            onChange={(event) => updateField("year", event.target.value)}
          />
          {yearError ? <small id="paper-review-year-error" role="alert">{yearError}</small> : null}
        </label>
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
          <select
            value={permittedStatuses.includes(form.review_status as ReviewStatus) ? form.review_status : ""}
            onChange={(event) => updateField("review_status", event.target.value)}
          >
            <option value="" disabled>{capabilities ? "Choose a permitted transition" : "Loading actor permissions..."}</option>
            {permittedStatuses.map((status) => (
              <option key={status} value={status}>
                {status.replaceAll("_", " ")}
              </option>
            ))}
          </select>
        </label>
        <TextField label="Reviewer notes" value={form.reviewer_notes} onChange={(value) => updateField("reviewer_notes", value)} />
      </div>
      <p className="field-help">Changing metadata creates a new reviewable version and returns the record to needs review.</p>
      <BusyButton
        busy={saving}
        busyLabel="Saving..."
        onClick={save}
        disabled={!capabilities?.capabilities.review || !permittedStatuses.includes(form.review_status as ReviewStatus)}
      >
        Save Metadata Review
      </BusyButton>
    </article>
  );
}

function ExtractionReview({
  preview,
  selectedItem,
  capabilities,
  onSaved,
  onError,
}: {
  preview: AdminPublicationPreview | null;
  selectedItem: ReviewQueueItem | null;
  capabilities: ActorCapabilities | null;
  onSaved: () => void;
  onError: (err: unknown) => void;
}) {
  const records = preview?.items ?? [];
  const [paperId, setPaperId] = useState(selectedItem?.item_id ?? records[0]?.paper_id ?? "");
  const [notes, setNotes] = useState("");
  const paper = records.find((record) => record.paper_id === paperId) ?? null;

  useEffect(() => {
    if (selectedItem?.item_id && records.some((record) => record.paper_id === selectedItem.item_id)) {
      setPaperId(selectedItem.item_id);
    } else if (!records.some((record) => record.paper_id === paperId)) {
      setPaperId(records[0]?.paper_id ?? "");
    }
  }, [paperId, records, selectedItem]);

  useEffect(() => {
    setNotes(paper?.extraction_reviewer_notes ?? "");
  }, [paper]);

  if (!paper) {
    return <EmptyState title="No extraction record is available for review" body="The protected publication preview has no paper extraction diagnostics." />;
  }

  const activePaper = paper;
  const warnings = extractionWarnings(activePaper);
  function save(status: ReviewStatus) {
    return reviewExtraction(activePaper.paper_id, {
      review_status: status,
      reviewer_notes: notes || undefined,
    }).then(onSaved);
  }

  return (
    <>
      <label className="admin-field">
        <span>Extraction record</span>
        <select value={paperId} onChange={(event) => setPaperId(event.target.value)}>
          {records.map((record) => <option key={record.paper_id} value={record.paper_id}>{record.title}</option>)}
        </select>
      </label>
      <ReviewCard
        title={`Extraction: ${activePaper.title}`}
        status={activePaper.extraction_review_status ?? "needs_review"}
        groundingStatus={null}
        warnings={warnings}
        notes={notes}
        onNotesChange={setNotes}
        onSave={save}
        onError={onError}
        capabilities={capabilities}
      >
        <p className="notice">Protected extraction diagnostics. Review the parser, OCR, title-match, and corpus-eligibility evidence before changing status.</p>
        <dl className="detail-list">
          <Detail label="Paper ID" value={activePaper.paper_id} />
          <Detail label="PDF text status" value={activePaper.pdf_text_status} />
          <Detail label="PDF unavailable reason" value={activePaper.pdf_unavailability_reason} />
          <Detail label="PDF unavailable detail" value={activePaper.pdf_unavailability_detail} />
          <Detail label="Possible scanned PDF" value={yesNoUnknown(activePaper.possible_scanned_pdf)} />
          <Detail label="Extraction content type" value={activePaper.extraction_content_type} />
          <Detail label="OCR status" value={activePaper.ocr_status} />
          <Detail label="OCR provider" value={activePaper.ocr_provider} />
          <Detail label="OCR provider version" value={activePaper.ocr_provider_version} />
          <Detail label="OCR pages" value={activePaper.ocr_pages_count} />
          <Detail label="OCR review required" value={yesNoUnknown(activePaper.ocr_review_required)} />
          <Detail label="PDF title match status" value={activePaper.pdf_title_match_status} />
          <Detail label="PDF title match score" value={activePaper.pdf_title_match_score} />
          <Detail label="Corpus eligibility" value={activePaper.corpus_eligibility_status} />
          <Detail label="Corpus exclusion reason" value={activePaper.corpus_exclusion_reason} />
        </dl>
      </ReviewCard>
    </>
  );
}

function GraphGovernanceReview({
  group,
  items,
  selectedItem,
  itemTypeFilter,
  total,
  offset,
  pageSize,
  onItemTypeChange,
  onOffsetChange,
  capabilities,
  onSaved,
  onError,
}: {
  group: "identities" | "topics";
  items: ReviewQueueItem[];
  selectedItem: ReviewQueueItem | null;
  itemTypeFilter: string;
  total: number;
  offset: number;
  pageSize: number;
  onItemTypeChange: (itemType: GraphReviewItemType) => void;
  onOffsetChange: (offset: number) => void;
  capabilities: ActorCapabilities | null;
  onSaved: () => void;
  onError: (err: unknown) => void;
}) {
  const acceptedTypes = GRAPH_GROUP_TYPES[group];
  const records = useMemo(
    () => items.filter((item) => acceptedTypes.includes(item.item_type as GraphReviewItemType)),
    [acceptedTypes, items],
  );
  const selectedBelongsToGroup = selectedItem && acceptedTypes.includes(selectedItem.item_type as GraphReviewItemType);
  const initialItem = selectedBelongsToGroup ? selectedItem : records[0] ?? null;
  const [selectedKey, setSelectedKey] = useState(initialItem ? graphItemKey(initialItem) : "");
  const [form, setForm] = useState<GraphGovernanceForm>(() => graphFormFrom(initialItem));
  const [baseline, setBaseline] = useState(() => graphCorrectionFingerprint(initialItem, graphFormFrom(initialItem)));
  const [notes, setNotes] = useState(() => graphReviewerNotes(initialItem));
  const [correctionError, setCorrectionError] = useState<string | null>(null);
  const [savingCorrection, setSavingCorrection] = useState(false);
  const [reviewPending, setReviewPending] = useState(false);
  const correctionMutationRef = useRef(false);
  const reviewMutationRef = useRef(false);

  const activeItem = records.find((item) => graphItemKey(item) === selectedKey)
    ?? (selectedBelongsToGroup ? selectedItem : null)
    ?? records[0]
    ?? null;

  useEffect(() => {
    if (selectedBelongsToGroup && selectedItem) {
      setSelectedKey(graphItemKey(selectedItem));
    } else if (!records.some((item) => graphItemKey(item) === selectedKey)) {
      setSelectedKey(records[0] ? graphItemKey(records[0]) : "");
    }
  }, [records, selectedBelongsToGroup, selectedItem, selectedKey]);

  useEffect(() => {
    const next = graphFormFrom(activeItem);
    setForm(next);
    setBaseline(graphCorrectionFingerprint(activeItem, next));
    setNotes(graphReviewerNotes(activeItem));
    setCorrectionError(null);
  }, [activeItem?.item_id, activeItem?.item_type, activeItem?.updated_at]);

  if (!activeItem || !isGraphQueueItem(activeItem)) {
    return (
      <section className="admin-card graph-record-picker" aria-labelledby={`${group}-queue-title`}>
        <GraphQueueHeader
          group={group}
          itemTypeFilter={itemTypeFilter}
          total={total}
          onItemTypeChange={onItemTypeChange}
        />
        <EmptyState
          title={group === "identities" ? "No author identity task matches this queue page" : "No topic or evidence-link task matches this queue page"}
          body="Change the record type or queue page. The public Explorer remains fail-closed until human approval."
        />
        <PaginationControls label={`${group} queue`} total={total} offset={offset} pageSize={pageSize} onOffsetChange={onOffsetChange} />
      </section>
    );
  }

  const itemType = activeItem.item_type;
  const approvalBlockers = graphApprovalBlockers(activeItem);
  const currentFingerprint = graphCorrectionFingerprint(activeItem, form);
  const correctionChanged = currentFingerprint !== baseline;

  function updateField(field: keyof GraphGovernanceForm, value: string) {
    setForm((current) => ({ ...current, [field]: value }));
    setCorrectionError(null);
  }

  function saveReview(status: ReviewStatus) {
    return reviewGraphRecord(itemType, activeItem.item_id, {
      review_status: status,
      reviewer_notes: notes.trim() || undefined,
    }).then(onSaved);
  }

  function saveCorrection() {
    if (correctionMutationRef.current || reviewMutationRef.current) return;
    const result = buildGraphCorrection(itemType, form);
    if (result.error) {
      setCorrectionError(result.error);
      return;
    }
    if (!result.body) {
      setCorrectionError("Change at least one correction field before saving.");
      return;
    }
    if (notes.trim()) result.body.reviewer_notes = notes.trim();
    setCorrectionError(null);
    correctionMutationRef.current = true;
    setSavingCorrection(true);
    saveGraphCorrection(itemType, activeItem.item_id, result.body)
      .then(onSaved)
      .catch(onError)
      .finally(() => {
        correctionMutationRef.current = false;
        setSavingCorrection(false);
      });
  }

  function setReviewMutationPending(pending: boolean) {
    reviewMutationRef.current = pending;
    setReviewPending(pending);
  }

  return (
    <>
      <section className="admin-card graph-record-picker" aria-labelledby={`${group}-queue-title`}>
        <GraphQueueHeader
          group={group}
          itemTypeFilter={itemTypeFilter}
          total={total}
          onItemTypeChange={onItemTypeChange}
        />
        <label className="admin-field">
          <span>Review record</span>
          <select value={graphItemKey(activeItem)} onChange={(event) => setSelectedKey(event.target.value)}>
            {records.map((record) => (
              <option key={graphItemKey(record)} value={graphItemKey(record)}>
                {record.item_type.replaceAll("_", " ")}: {record.title}
              </option>
            ))}
          </select>
        </label>
        <p className="field-help">Only the current protected queue page is listed here. Corrections create a new needs-review version; they never approve a record.</p>
        <PaginationControls label={`${group} queue`} total={total} offset={offset} pageSize={pageSize} onOffsetChange={onOffsetChange} />
      </section>

      <ReviewCard
        title={activeItem.title}
        status={activeItem.status}
        groundingStatus={null}
        warnings={activeItem.warnings}
        notes={notes}
        onNotesChange={setNotes}
        onSave={saveReview}
        onError={onError}
        capabilities={capabilities}
        approvalBlockers={approvalBlockers}
        externalMutationPending={savingCorrection}
        onMutationPendingChange={setReviewMutationPending}
      >
        <div className="paper-card__badges paper-card__badges--left">
          <StatusBadge label={itemType} tone="info" />
          {itemType === "author" ? <StatusBadge label={getString(activeItem.details, "identity_status") || "unresolved"} tone={identityTone(getString(activeItem.details, "identity_status"))} /> : null}
          <StatusBadge label={getString(activeItem.details, "source") || "source not recorded"} />
        </div>

        <p className="notice">
          Source-derived labels and links are review candidates, not verified identities or expertise claims. AI and service actors may correct or mark their own review state, but only an authenticated human administrator can approve or reject them.
        </p>
        {approvalBlockers.length ? (
          <div className="notice notice--warning" role="status">
            <strong>Approval blocked</strong>
            <ul>{approvalBlockers.map((blocker) => <li key={blocker}>{approvalBlockerLabel(blocker)}</li>)}</ul>
          </div>
        ) : null}

        <GraphEvidence item={activeItem} />

        <fieldset className="governance-correction-fields">
          <legend>Correction candidate</legend>
          {itemType === "author" ? (
            <>
              <div className="admin-form-grid">
                <TextField label="Canonical author name" value={form.canonical_name} onChange={(value) => updateField("canonical_name", value)} />
                <label className="admin-field">
                  <span>Identity status</span>
                  <select value={form.identity_status} onChange={(event) => updateField("identity_status", event.target.value)}>
                    <option value="unresolved">Unresolved</option>
                    <option value="ambiguous">Ambiguous</option>
                    <option value="resolved">Resolved</option>
                    <option value="merged">Merged</option>
                    <option value="invalid">Invalid parser artifact</option>
                  </select>
                </label>
                <label className="admin-field">
                  <span>Merged into author ID</span>
                  <input type="number" inputMode="numeric" min={1} step={1} value={form.merged_into_author_id} disabled={form.identity_status !== "merged"} onChange={(event) => updateField("merged_into_author_id", event.target.value)} />
                </label>
                <TextField label="Affiliation" value={form.affiliation} onChange={(value) => updateField("affiliation", value)} />
                <TextField label="Email" value={form.email} onChange={(value) => updateField("email", value)} />
                <TextField label="Profile URL" value={form.profile_url} onChange={(value) => updateField("profile_url", value)} />
                <TextField label="Persistent identifier" value={form.persistent_identifier} onChange={(value) => updateField("persistent_identifier", value)} />
                <TextField label="Identifier source" value={form.persistent_identifier_source} onChange={(value) => updateField("persistent_identifier_source", value)} />
              </div>
              <p className="field-help">Choose resolved only when the canonical identity is supported. Ambiguity must remain explicit; a merge requires a distinct target author ID.</p>
            </>
          ) : null}

          {itemType === "author_alias" ? (
            <div className="admin-form-grid admin-form-grid--small">
              <TextField label="Alias text" value={form.alias} onChange={(value) => updateField("alias", value)} />
              <label className="admin-field">
                <span>Canonical author ID</span>
                <input type="number" inputMode="numeric" min={1} step={1} value={form.canonical_author_id} onChange={(event) => updateField("canonical_author_id", event.target.value)} />
              </label>
            </div>
          ) : null}

          {itemType === "topic" ? (
            <div className="admin-form-grid admin-form-grid--small">
              <TextField label="Topic name" value={form.name} onChange={(value) => updateField("name", value)} />
              <label className="admin-field">
                <span>Topic description</span>
                <textarea value={form.description} onChange={(event) => updateField("description", event.target.value)} rows={4} />
              </label>
              <p className="field-help">Changing a topic returns its paper-topic and author-topic links to needs review.</p>
            </div>
          ) : null}

          {itemType === "paper_topic" || itemType === "author_topic" ? (
            <>
              <div className="admin-form-grid admin-form-grid--small">
                {itemType === "author_topic" ? (
                  <label className="admin-field">
                    <span>Supporting paper count</span>
                    <input type="number" inputMode="numeric" min={0} step={1} value={form.paper_count} onChange={(event) => updateField("paper_count", event.target.value)} />
                  </label>
                ) : null}
                <label className="admin-field">
                  <span>Evidence score</span>
                  <input type="number" inputMode="decimal" min={0} step="any" value={form.score} onChange={(event) => updateField("score", event.target.value)} />
                </label>
              </div>
              <label className="admin-field">
                <span>Evidence locators (JSON array)</span>
                <textarea value={form.evidence_json} onChange={(event) => updateField("evidence_json", event.target.value)} rows={10} spellCheck={false} />
              </label>
              <p className="field-help">Evidence locators must remain source-derived. A score is a ranking signal, not proof of topical relevance or researcher expertise.</p>
            </>
          ) : null}
        </fieldset>

        {correctionError ? <p className="notice notice--error" role="alert">{correctionError}</p> : null}
        <BusyButton
          variant="secondary"
          busy={savingCorrection}
          busyLabel="Saving correction..."
          onClick={saveCorrection}
          disabled={!capabilities?.capabilities.save_corrections || !correctionChanged || savingCorrection || reviewPending}
        >
          Save Correction (returns to needs review)
        </BusyButton>
      </ReviewCard>
    </>
  );
}

function GraphQueueHeader({
  group,
  itemTypeFilter,
  total,
  onItemTypeChange,
}: {
  group: "identities" | "topics";
  itemTypeFilter: string;
  total: number;
  onItemTypeChange: (itemType: GraphReviewItemType) => void;
}) {
  const options = group === "identities"
    ? [
        ["author", "Author identities"],
        ["author_alias", "Author aliases"],
      ] as const
    : [
        ["topic", "Topics"],
        ["paper_topic", "Paper-topic evidence links"],
        ["author_topic", "Author-topic evidence links"],
      ] as const;
  const selectedType = options.some(([value]) => value === itemTypeFilter)
    ? itemTypeFilter
    : options[0][0];
  return (
    <>
      <div className="section-heading section-heading--compact">
        <div>
          <p className="eyebrow">Protected evidence-governance queue</p>
          <h2 id={`${group}-queue-title`}>{group === "identities" ? "Author identity and alias tasks" : "Topic and evidence-link tasks"}</h2>
        </div>
        <StatusBadge label={`${total} matching records`} tone="warn" />
      </div>
      <label className="admin-field">
        <span>Record type</span>
        <select value={selectedType} onChange={(event) => onItemTypeChange(event.target.value as GraphReviewItemType)}>
          {options.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </label>
    </>
  );
}

function GraphEvidence({ item }: { item: ReviewQueueItem }) {
  const details = item.details;
  const identities = item.item_type === "author" || item.item_type === "author_alias";
  return (
    <section aria-labelledby={`graph-evidence-${item.item_type}-${item.item_id}`}>
      <h3 id={`graph-evidence-${item.item_type}-${item.item_id}`}>Recorded source and dependency evidence</h3>
      <dl className="detail-list">
        <Detail label="Record ID" value={item.item_id} />
        <Detail label="Raw/source name" value={getString(details, item.item_type === "author_alias" ? "alias" : "name")} />
        <Detail label="Canonical name" value={getString(details, "canonical_name")} />
        <Detail label="Normalized value" value={getString(details, item.item_type === "author_alias" ? "normalized_alias" : "normalized_name")} />
        <Detail label="Identity status" value={getString(details, "identity_status")} />
        <Detail label="Canonical author ID" value={getStringOrNumber(details, "canonical_author_id")} />
        <Detail label="Paper ID" value={getString(details, "paper_id")} />
        <Detail label="Author ID" value={getStringOrNumber(details, "author_id")} />
        <Detail label="Topic ID" value={getString(details, "topic_id")} />
        <Detail label="Source" value={getString(details, "source")} />
        <Detail label="Evidence score" value={getStringOrNumber(details, "score")} />
        <Detail label="Supporting papers" value={getStringOrNumber(details, "paper_count")} />
        {identities ? <Detail label="Persistent identifier" value={getString(details, "persistent_identifier")} /> : null}
        {identities ? <Detail label="Identifier source" value={getString(details, "persistent_identifier_source")} /> : null}
      </dl>
      <StructuredPreview value={details.dependencies} title="Approval dependency state" />
      <StructuredPreview value={details.evidence_json} title="Source evidence locators" />
      <StructuredPreview value={details.research_topics} title="Derived research topics" />
    </section>
  );
}

function GeneratedArtifactReview({
  item,
  capabilities,
  onSaved,
  onError,
}: {
  item: ReviewQueueItem | null;
  capabilities: ActorCapabilities | null;
  onSaved: () => void;
  onError: (err: unknown) => void;
}) {
  const [notes, setNotes] = useState("");
  const [correctedText, setCorrectedText] = useState("");
  const [correctionTextBaseline, setCorrectionTextBaseline] = useState("");
  const [correctedJsonText, setCorrectedJsonText] = useState("");
  const [correctionJsonBaseline, setCorrectionJsonBaseline] = useState("");
  const [correctionError, setCorrectionError] = useState<string | null>(null);
  const [savingCorrection, setSavingCorrection] = useState(false);
  const [reviewPending, setReviewPending] = useState(false);
  const correctionMutationRef = useRef(false);
  const reviewMutationRef = useRef(false);

  useEffect(() => {
    setNotes(getString(item?.details, "reviewer_notes"));
    const textCandidate = item?.details.corrected_text !== null && item?.details.corrected_text !== undefined
      ? getString(item.details, "corrected_text")
      : getString(item?.details, "generated_text");
    const jsonCandidate = item?.details.corrected_json ?? item?.details.generated_json;
    const serializedJson = jsonCandidate === null || jsonCandidate === undefined ? "" : JSON.stringify(jsonCandidate, null, 2);
    setCorrectedText(textCandidate);
    setCorrectionTextBaseline(textCandidate);
    setCorrectedJsonText(serializedJson);
    setCorrectionJsonBaseline(serializedJson);
    setCorrectionError(null);
  }, [item]);

  if (!item) {
    return <EmptyState title="No paper artifact selected" body="Open an artifact from the review queue to inspect generated content and citations." />;
  }
  const activeItem = item;

  function save(status: ReviewStatus) {
    return reviewArtifact(activeItem.item_id, {
      review_status: status,
      reviewer_notes: notes,
    }).then(onSaved);
  }

  function saveCorrection() {
    if (correctionMutationRef.current || reviewMutationRef.current) return;
    const body: { corrected_text?: string; corrected_json?: Record<string, unknown>; reviewer_notes?: string } = {
      reviewer_notes: notes || undefined,
    };
    if (textCorrectionChanged) body.corrected_text = correctedText;
    if (jsonCorrectionChanged) {
      try {
        const parsed = JSON.parse(correctedJsonText) as unknown;
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
          throw new Error("Structured correction must be a JSON object.");
        }
        body.corrected_json = parsed as Record<string, unknown>;
      } catch (err) {
        setCorrectionError(err instanceof Error ? err.message : "Structured correction is not valid JSON.");
        return;
      }
    }
    setCorrectionError(null);
    correctionMutationRef.current = true;
    setSavingCorrection(true);
    saveArtifactCorrection(activeItem.item_id, body)
      .then(onSaved)
      .catch(onError)
      .finally(() => {
        correctionMutationRef.current = false;
        setSavingCorrection(false);
      });
  }

  function setReviewMutationPending(pending: boolean) {
    reviewMutationRef.current = pending;
    setReviewPending(pending);
  }

  const textCorrectionChanged = correctedText !== correctionTextBaseline;
  const jsonCorrectionChanged = correctedJsonText !== correctionJsonBaseline;
  const correctionChanged = textCorrectionChanged || jsonCorrectionChanged;
  const hasTextCorrection = Object.prototype.hasOwnProperty.call(activeItem.details, "corrected_text")
    && activeItem.details.corrected_text !== null;

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
      capabilities={capabilities}
      externalMutationPending={savingCorrection}
      onMutationPendingChange={setReviewMutationPending}
    >
      <section aria-labelledby="generated-artifact-content">
        <h3 id="generated-artifact-content">Generated source output</h3>
        <p>{getString(activeItem.details, "generated_text") || "Generated text is stored as structured JSON for this artifact."}</p>
        <StructuredPreview value={activeItem.details.generated_json} title="Generated structured fields" />
      </section>
      <label className="admin-field">
        <span>Reviewer-corrected text</span>
        <textarea value={correctedText} onChange={(event) => setCorrectedText(event.target.value)} rows={5} />
      </label>
      <p className="field-help">
        {hasTextCorrection
          ? "A reviewer correction is stored. Saving another correction creates a new reviewable version."
          : "No reviewer correction is stored. Saving one returns this artifact to needs review before it can be approved."}
      </p>
      <label className="admin-field">
        <span>Reviewer-corrected structured JSON</span>
        <textarea
          value={correctedJsonText}
          onChange={(event) => { setCorrectedJsonText(event.target.value); setCorrectionError(null); }}
          rows={10}
          spellCheck={false}
        />
      </label>
      {correctionError ? <p className="notice notice--error" role="alert">{correctionError}</p> : null}
      <BusyButton
        variant="secondary"
        busy={savingCorrection}
        busyLabel="Saving correction..."
        onClick={saveCorrection}
        disabled={!capabilities?.capabilities.save_corrections || !correctionChanged || savingCorrection || reviewPending}
      >
        Save Correction (returns to needs review)
      </BusyButton>
      <CitationPreview details={activeItem.details} />
    </ReviewCard>
  );
}

function AskAnswerReview({ item, capabilities, onSaved, onError }: { item: ReviewQueueItem | null; capabilities: ActorCapabilities | null; onSaved: () => void; onError: (err: unknown) => void }) {
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
      capabilities={capabilities}
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

function ThesisRecommendationReview({ item, capabilities, onSaved, onError }: { item: ReviewQueueItem | null; capabilities: ActorCapabilities | null; onSaved: () => void; onError: (err: unknown) => void }) {
  const [notes, setNotes] = useState("");
  const [correctionText, setCorrectionText] = useState("");
  const [correctionBaseline, setCorrectionBaseline] = useState("");
  const [correctionError, setCorrectionError] = useState<string | null>(null);
  const [savingCorrection, setSavingCorrection] = useState(false);
  const [reviewPending, setReviewPending] = useState(false);
  const correctionMutationRef = useRef(false);
  const reviewMutationRef = useRef(false);

  useEffect(() => {
    setNotes(getString(item?.details, "reviewer_notes"));
    const value = item?.details.corrected_recommendations_json ?? item?.details.recommendations ?? [];
    const serialized = JSON.stringify(value, null, 2);
    setCorrectionText(serialized);
    setCorrectionBaseline(serialized);
    setCorrectionError(null);
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

  function saveCorrection() {
    if (correctionMutationRef.current || reviewMutationRef.current) return;
    let parsed: unknown;
    try {
      parsed = JSON.parse(correctionText);
    } catch {
      setCorrectionError("Correction must be valid JSON.");
      return;
    }
    if (!Array.isArray(parsed) && (parsed === null || typeof parsed !== "object")) {
      setCorrectionError("Correction must be a JSON object or an array of recommendation objects.");
      return;
    }
    if (Array.isArray(parsed) && parsed.some((value) => value === null || typeof value !== "object" || Array.isArray(value))) {
      setCorrectionError("Every recommendation in the correction array must be a JSON object.");
      return;
    }
    setCorrectionError(null);
    correctionMutationRef.current = true;
    setSavingCorrection(true);
    saveRecommendationCorrection(activeItem.item_id, {
      corrected_recommendations_json: parsed as Record<string, unknown> | Record<string, unknown>[],
      reviewer_notes: notes || undefined,
    })
      .then(onSaved)
      .catch(onError)
      .finally(() => {
        correctionMutationRef.current = false;
        setSavingCorrection(false);
      });
  }

  function setReviewMutationPending(pending: boolean) {
    reviewMutationRef.current = pending;
    setReviewPending(pending);
  }

  const generatedRecommendations = getArray(activeItem.details, "recommendations");
  const correctedValue = activeItem.details.corrected_recommendations_json;
  const hasCorrection = correctedValue !== null && correctedValue !== undefined;
  const recommendations = hasCorrection ? recommendationItems(correctedValue) : generatedRecommendations;
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
      capabilities={capabilities}
      externalMutationPending={savingCorrection}
      onMutationPendingChange={setReviewMutationPending}
    >
      <StructuredPreview value={activeItem.details.request} title="Student request" />
      <StructuredPreview value={generatedRecommendations} title="Original generated recommendation fields" />
      {hasCorrection ? (
        <>
          <p className="notice" role="status">Reviewer-corrected recommendation fields are stored and shown below as the effective review candidate.</p>
          <StructuredPreview value={correctedValue} title="Reviewer-corrected recommendation fields" />
        </>
      ) : null}
      <label className="admin-field">
        <span>Reviewer-corrected recommendation JSON</span>
        <textarea
          value={correctionText}
          onChange={(event) => { setCorrectionText(event.target.value); setCorrectionError(null); }}
          rows={12}
          spellCheck={false}
        />
      </label>
      <p className="field-help">Saving a structured correction preserves the generated version and returns the recommendation to needs review.</p>
      {correctionError ? <p className="notice notice--error" role="alert">{correctionError}</p> : null}
      <BusyButton
        variant="secondary"
        busy={savingCorrection}
        busyLabel="Saving correction..."
        onClick={saveCorrection}
        disabled={!capabilities?.capabilities.save_corrections || correctionText === correctionBaseline || savingCorrection || reviewPending}
      >
        Save Recommendation Correction (returns to needs review)
      </BusyButton>
      <StructuredPreview value={activeItem.details.effective_provenance} title="Approved-version provenance" />
      <div className="paper-list">
        {recommendations.map((value, index) => {
          const recommendation = asRecord(value);
          return (
            <article className="citation-card" key={`${activeItem.item_id}-${index}`}>
              <h3>{getString(recommendation, "extension_title") || getString(recommendation, "paper_title") || `Recommendation ${index + 1}`}</h3>
              <p>{getString(recommendation, "why_it_fits_student")}</p>
              <p>{getString(recommendation, "extension_summary")}</p>
              <StructuredPreview value={recommendation} title="All recommendation fields" />
              <CitationPreview details={recommendation} />
            </article>
          );
        })}
      </div>
    </ReviewCard>
  );
}

function ReviewEventsPanel({
  events,
  total,
  offset,
  pageSize,
  onOffsetChange,
}: {
  events: ReviewEvent[];
  total: number;
  offset: number;
  pageSize: number;
  onOffsetChange: (offset: number) => void;
}) {
  return (
    <>
      <div className="section-heading">
        <h2>Review Events</h2>
        <span className="queue-count">{total} events</span>
      </div>
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
      <PaginationControls label="Review events" total={total} offset={offset} pageSize={pageSize} onOffsetChange={onOffsetChange} />
    </>
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
  capabilities,
  approvalBlockers = [],
  externalMutationPending = false,
  onMutationPendingChange,
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
  capabilities: ActorCapabilities | null;
  approvalBlockers?: string[];
  externalMutationPending?: boolean;
  onMutationPendingChange?: (pending: boolean) => void;
  children: ReactNode;
}) {
  const [savingStatus, setSavingStatus] = useState<ReviewStatus | null>(null);
  const statusMutationRef = useRef(false);
  const mutationPending = savingStatus !== null || externalMutationPending;
  const allowedTargets = allowedReviewTargets(status, capabilities).filter(
    (target) => target !== status && !(target === "approved" && approvalBlockers.length),
  );

  function save(status: ReviewStatus) {
    if (statusMutationRef.current || externalMutationPending) return;
    statusMutationRef.current = true;
    setSavingStatus(status);
    onMutationPendingChange?.(true);
    Promise.resolve()
      .then(() => onSave(status))
      .catch(onError)
      .finally(() => {
        statusMutationRef.current = false;
        setSavingStatus(null);
        onMutationPendingChange?.(false);
      });
  }

  return (
    <article className="admin-card" aria-busy={mutationPending}>
      <div className="paper-card__badges paper-card__badges--left">
        <StatusBadge label={status} />
        {groundingStatus ? <StatusBadge label={groundingStatus} /> : null}
      </div>
      <h2>{title}</h2>
      {warnings.length ? <p className="notice notice--warning">{warnings.join(" ")}</p> : null}
      <fieldset className="review-card__mutation-controls" disabled={mutationPending}>
        <legend className="sr-only">Review controls for {title}</legend>
        {children}
        <label className="admin-field">
          <span>Reviewer notes</span>
          <textarea value={notes} onChange={(event) => onNotesChange(event.target.value)} rows={4} />
        </label>
        <div className="admin-action-row">
          {allowedTargets.map((target) => (
            <BusyButton
              key={target}
              variant={reviewActionVariant(target)}
              busy={savingStatus === target}
              busyLabel={`${reviewActionLabel(target)}...`}
              onClick={() => save(target)}
              disabled={mutationPending}
            >
              {reviewActionLabel(target)}
            </BusyButton>
          ))}
        </div>
      </fieldset>
      {!capabilities ? <p className="field-help">Loading actor permissions before review actions are shown.</p> : null}
      {capabilities && approvalBlockers.length && allowedReviewTargets(status, capabilities).includes("approved") ? (
        <p className="field-help">Approval is withheld until the record-level blockers above are resolved and the corrected record is re-reviewed.</p>
      ) : null}
      {capabilities && !allowedTargets.length ? <p className="field-help">No further review transition is permitted for this actor and current state.</p> : null}
    </article>
  );
}

function PaginationControls({
  label,
  total,
  offset,
  pageSize,
  onOffsetChange,
}: {
  label: string;
  total: number;
  offset: number;
  pageSize: number;
  onOffsetChange: (offset: number) => void;
}) {
  if (total <= 0) return null;
  const start = offset + 1;
  const end = Math.min(offset + pageSize, total);
  return (
    <nav className="pagination-controls" aria-label={`${label} pagination`}>
      <p>Showing {start}–{end} of {total}</p>
      <div className="admin-action-row">
        <button
          className="action-button action-button--secondary"
          disabled={offset === 0}
          onClick={() => onOffsetChange(Math.max(0, offset - pageSize))}
        >
          Previous
        </button>
        <button
          className="action-button action-button--secondary"
          disabled={offset + pageSize >= total}
          onClick={() => onOffsetChange(offset + pageSize)}
        >
          Next
        </button>
      </div>
    </nav>
  );
}

function Detail({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value === null || value === undefined || value === "" ? "Not recorded" : value}</dd>
    </div>
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

function isGraphQueueItem(
  item: ReviewQueueItem | null,
): item is ReviewQueueItem & { item_type: GraphReviewItemType } {
  return Boolean(item && ["author", "author_alias", "topic", "paper_topic", "author_topic"].includes(item.item_type));
}

function graphItemKey(item: ReviewQueueItem): string {
  return `${item.item_type}:${item.item_id}`;
}

function graphReviewerNotes(item: ReviewQueueItem | null): string {
  if (!item) return "";
  return getString(item.details, item.item_type === "author" ? "identity_review_notes" : "reviewer_notes");
}

function graphFormFrom(item: ReviewQueueItem | null): GraphGovernanceForm {
  const details = item?.details;
  const evidence = details?.evidence_json;
  return {
    canonical_name: getString(details, "canonical_name"),
    affiliation: getString(details, "affiliation"),
    email: getString(details, "email"),
    profile_url: getString(details, "profile_url"),
    persistent_identifier: getString(details, "persistent_identifier"),
    persistent_identifier_source: getString(details, "persistent_identifier_source"),
    identity_status: getString(details, "identity_status") || "unresolved",
    merged_into_author_id: getStringOrNumber(details ?? {}, "merged_into_author_id"),
    alias: getString(details, "alias"),
    canonical_author_id: getStringOrNumber(details ?? {}, "canonical_author_id"),
    name: getString(details, "name"),
    description: getString(details, "description"),
    score: getStringOrNumber(details ?? {}, "score"),
    paper_count: getStringOrNumber(details ?? {}, "paper_count"),
    evidence_json: JSON.stringify(Array.isArray(evidence) ? evidence : [], null, 2),
  };
}

function graphCorrectionFingerprint(item: ReviewQueueItem | null, form: GraphGovernanceForm): string {
  if (!item || !isGraphQueueItem(item)) return "";
  const result = buildGraphCorrection(item.item_type, form);
  return result.body ? JSON.stringify(result.body) : JSON.stringify(form);
}

function buildGraphCorrection(
  itemType: GraphReviewItemType,
  form: GraphGovernanceForm,
): { body: Record<string, unknown> | null; error: string | null } {
  if (itemType === "author") {
    const canonicalName = form.canonical_name.trim();
    if (form.identity_status === "resolved" && !canonicalName) {
      return { body: null, error: "A resolved identity requires a canonical author name." };
    }
    const mergeTarget = parseOptionalPositiveInteger(form.merged_into_author_id);
    if (mergeTarget.error) return { body: null, error: `Merged author ID: ${mergeTarget.error}` };
    if (form.identity_status === "merged" && mergeTarget.value === null) {
      return { body: null, error: "A merged identity requires a target author ID." };
    }
    return {
      body: {
        canonical_name: canonicalName || null,
        affiliation: blankToNull(form.affiliation),
        email: blankToNull(form.email),
        profile_url: blankToNull(form.profile_url),
        persistent_identifier: blankToNull(form.persistent_identifier),
        persistent_identifier_source: blankToNull(form.persistent_identifier_source),
        identity_status: form.identity_status,
        merged_into_author_id: form.identity_status === "merged" ? mergeTarget.value : null,
      },
      error: null,
    };
  }

  if (itemType === "author_alias") {
    const alias = form.alias.trim();
    if (!alias) return { body: null, error: "Alias text is required." };
    const authorId = parseOptionalPositiveInteger(form.canonical_author_id);
    if (authorId.error || authorId.value === null) {
      return { body: null, error: `Canonical author ID: ${authorId.error || "a positive integer is required."}` };
    }
    return { body: { alias, canonical_author_id: authorId.value }, error: null };
  }

  if (itemType === "topic") {
    const name = form.name.trim();
    if (!name) return { body: null, error: "Topic name is required." };
    return { body: { name, description: blankToNull(form.description) }, error: null };
  }

  const score = Number(form.score);
  if (!form.score.trim() || !Number.isFinite(score) || score < 0) {
    return { body: null, error: "Evidence score must be a finite number greater than or equal to zero." };
  }
  const evidence = parseEvidenceJson(form.evidence_json);
  if (evidence.error) return { body: null, error: evidence.error };

  if (itemType === "paper_topic") {
    return { body: { score, evidence_json: evidence.value }, error: null };
  }

  const paperCount = Number(form.paper_count);
  if (!form.paper_count.trim() || !Number.isInteger(paperCount) || paperCount < 0) {
    return { body: null, error: "Supporting paper count must be a whole number greater than or equal to zero." };
  }
  return { body: { paper_count: paperCount, score, evidence_json: evidence.value }, error: null };
}

function parseEvidenceJson(value: string): { value: Record<string, unknown>[]; error: string | null } {
  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch {
    return { value: [], error: "Evidence locators must be valid JSON." };
  }
  if (!Array.isArray(parsed) || parsed.some((entry) => !entry || typeof entry !== "object" || Array.isArray(entry))) {
    return { value: [], error: "Evidence locators must be a JSON array of objects." };
  }
  return { value: parsed as Record<string, unknown>[], error: null };
}

function parseOptionalPositiveInteger(value: string): { value: number | null; error: string | null } {
  if (!value.trim()) return { value: null, error: null };
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 1) {
    return { value: null, error: "enter a positive whole number." };
  }
  return { value: parsed, error: null };
}

function blankToNull(value: string): string | null {
  const normalized = value.trim();
  return normalized || null;
}

function graphApprovalBlockers(item: ReviewQueueItem): string[] {
  const blockers = item.approval_blockers ?? getStringArray(item.details, "approval_blockers");
  if (
    item.item_type === "author"
    && ["unresolved", "ambiguous"].includes(getString(item.details, "identity_status"))
    && !blockers.includes("identity_unresolved_or_ambiguous")
  ) {
    return [...blockers, "identity_unresolved_or_ambiguous"];
  }
  return blockers;
}

function approvalBlockerLabel(code: string): string {
  return {
    identity_unresolved_or_ambiguous: "The identity is unresolved or ambiguous; record a source-supported correction before approval.",
    canonical_metadata_missing: "Canonical identity metadata is missing.",
    merge_target_not_approved: "The merge target is not an approved resolved identity.",
    author_missing: "The linked author record is missing.",
    author_not_approved: "The linked author record is not approved.",
    author_identity_not_approved: "The linked author identity has not received human approval.",
    author_not_resolved: "The linked author identity is not resolved.",
    paper_missing: "The linked paper record is missing.",
    paper_metadata_not_approved: "The linked paper metadata has not received human approval.",
    topic_missing: "The linked topic record is missing.",
    topic_not_approved: "The linked topic has not received human approval.",
  }[code] ?? code.replaceAll("_", " ");
}

function identityTone(status: string): "good" | "warn" | "danger" | "neutral" {
  if (status === "resolved") return "good";
  if (status === "invalid") return "danger";
  if (status === "unresolved" || status === "ambiguous") return "warn";
  return "neutral";
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
  if (itemType === "author" || itemType === "author_alias") {
    return "identities";
  }
  if (itemType === "topic" || itemType === "paper_topic" || itemType === "author_topic") {
    return "topics";
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

function parsePaperYear(value: string): { value: number | null; error: string | null } {
  const normalized = value.trim();
  if (!normalized) return { value: null, error: null };
  const year = Number(normalized);
  if (!Number.isInteger(year) || year < 1800 || year > 2200) {
    return { value: null, error: "Enter a whole year from 1800 through 2200, or leave it blank." };
  }
  return { value: year, error: null };
}

function allowedReviewTargets(status: string, capabilities: ActorCapabilities | null): ReviewStatus[] {
  if (!capabilities?.capabilities.review) return [];
  return capabilities.allowed_review_transitions[status] ?? [];
}

function reviewActionLabel(status: ReviewStatus): string {
  return {
    needs_review: "Return to Needs Review",
    ai_reviewed: "Mark AI Reviewed",
    reviewed: "Mark Reviewed",
    approved: "Approve",
    rejected: "Reject",
    needs_reprocess: "Needs Reprocess",
  }[status];
}

function reviewActionVariant(status: ReviewStatus): "primary" | "secondary" | "danger" {
  if (status === "rejected") return "danger";
  if (status === "approved" || status === "reviewed" || status === "ai_reviewed") return "primary";
  return "secondary";
}

function recommendationItems(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  const record = asRecord(value);
  if (Array.isArray(record.items)) return record.items;
  if (Array.isArray(record.recommendations)) return record.recommendations;
  return [];
}

function extractionWarnings(paper: AdminPublicationPreviewPaper): string[] {
  const warnings: string[] = [];
  if (paper.pdf_unavailability_reason) warnings.push(`PDF unavailable: ${paper.pdf_unavailability_reason}.`);
  if (paper.possible_scanned_pdf) warnings.push("The source may be a scanned PDF.");
  if (paper.ocr_review_required) warnings.push("OCR output requires human review.");
  if (paper.pdf_title_match_status && !["matched", "match"].includes(paper.pdf_title_match_status.toLowerCase())) {
    warnings.push(`PDF title match is ${paper.pdf_title_match_status}.`);
  }
  if (paper.corpus_eligibility_status !== "eligible") {
    warnings.push(`Paper is not searchable: ${paper.corpus_exclusion_reason || paper.corpus_eligibility_status}.`);
  }
  return warnings;
}

function yesNoUnknown(value: boolean | undefined): string {
  if (value === undefined) return "Not recorded";
  return value ? "Yes" : "No";
}

function formatDate(value: string): string {
  return new Date(value).toLocaleString();
}
