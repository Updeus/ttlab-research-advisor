import { json } from "./fixtures";

export type GraphRequest = { path: string; body: Record<string, unknown> };

const overview = {
  papers_total: 0,
  papers_needing_metadata_review: 0,
  papers_missing_pdfs: 0,
  papers_with_extraction_failures: 0,
  possible_scanned_pdfs: 0,
  total_chunks: 0,
  rag_answers: {},
  rag_answers_by_grounding: {},
  thesis_recommendations: {},
  thesis_recommendations_by_grounding: {},
  paper_artifacts: {},
  paper_artifacts_by_grounding: {},
  paper_artifacts_by_type: {},
  artifacts_needing_review: 0,
  total_review_events: 0,
  recent_review_events: [],
};

const preview = { surface: "local_review_preview", public: false, notice: "Protected reviewer preview.", items: [] };

const sync = {
  source: "ttlab",
  enabled: false,
  schedule: "disabled",
  timezone: "America/La_Paz",
  run_on_startup: false,
  worker_poll_seconds: 30,
  download_pdfs: false,
  dense_index_policy: "never",
  manual_trigger_allowed: false,
  running: false,
  manual_request_pending: false,
  manual_requested_at: null,
  manual_requested_by: null,
  last_success_at: null,
  last_failure_at: null,
  next_scheduled_at: null,
  last_run: null,
  recent_runs: [],
};

const humanCapabilities = {
  actor: { actor_id: "human-admin", role: "admin", reviewer_type: "human", local_demo_bypass: false },
  capabilities: {
    review: true,
    save_corrections: true,
    approve_or_reject: true,
    set_publication_and_rights: true,
    trigger_ingestion: false,
  },
  allowed_review_transitions: {
    needs_review: ["needs_review", "reviewed", "approved", "rejected", "needs_reprocess"],
    ai_reviewed: ["needs_review", "approved", "rejected", "needs_reprocess"],
    reviewed: ["needs_review", "approved", "rejected", "needs_reprocess"],
    approved: ["needs_review", "needs_reprocess"],
    rejected: ["needs_review", "needs_reprocess"],
    needs_reprocess: ["needs_review", "reviewed", "rejected", "needs_reprocess"],
  },
};

const author = queueItem("author", "7", "Pat Example", {
  author_id: 7,
  name: "P. Example",
  canonical_name: null,
  normalized_name: "p example",
  affiliation: null,
  email: null,
  profile_url: null,
  research_topics: ["retrieval"],
  paper_count: 2,
  review_status: "needs_review",
  identity_status: "unresolved",
  identity_review_status: "needs_review",
  identity_review_notes: "Ambiguous initials",
  merged_into_author_id: null,
  persistent_identifier: null,
  persistent_identifier_source: null,
  approval_blockers: ["identity_unresolved_or_ambiguous"],
});

const alias = queueItem("author_alias", "alias-1", "P Example", {
  alias_id: "alias-1",
  alias: "P Example",
  normalized_alias: "p example",
  canonical_author_id: 8,
  source: "seed_import",
  review_status: "needs_review",
  reviewer_notes: "",
  approval_blockers: [],
  dependencies: { author: { author_id: 8, exists: true, review_status: "approved", identity_review_status: "approved", identity_status: "resolved" } },
});

const topic = queueItem("topic", "rag", "RAG", {
  topic_id: "rag",
  name: "RAG",
  normalized_name: "rag",
  description: "Retrieval-augmented generation",
  source: "deterministic_explorer",
  review_status: "needs_review",
  reviewer_notes: "",
  approval_blockers: [],
});

const paperTopic = queueItem("paper_topic", "pt-1", "Paper -> RAG", {
  link_id: "pt-1",
  paper_id: "paper-1",
  topic_id: "rag",
  score: 0.5,
  evidence_json: [{ source: "paper_metadata", field: "topics", value: "RAG" }],
  source: "deterministic_explorer",
  review_status: "needs_review",
  reviewer_notes: "",
  approval_blockers: ["paper_metadata_not_approved"],
  dependencies: {
    paper: { paper_id: "paper-1", exists: true, review_status: "needs_review" },
    topic: { topic_id: "rag", exists: true, review_status: "approved" },
  },
});

const authorTopic = queueItem("author_topic", "at-1", "Pat Example -> RAG", {
  link_id: "at-1",
  author_id: 8,
  topic_id: "rag",
  paper_count: 2,
  score: 1.5,
  evidence_json: [{ paper_id: "paper-1", source: "approved_paper_topic" }],
  review_status: "needs_review",
  reviewer_notes: "",
  approval_blockers: [],
  dependencies: {
    author: { author_id: 8, exists: true, review_status: "approved", identity_review_status: "approved", identity_status: "resolved" },
    topic: { topic_id: "rag", exists: true, review_status: "approved" },
  },
});

const itemsByType = {
  author: [author],
  author_alias: [alias],
  topic: [topic],
  paper_topic: [paperTopic],
  author_topic: [authorTopic],
} as const;

export function installGraphAdminFetch(
  requests: GraphRequest[],
  requestedQueues: string[] = [],
  options: { total?: number } = {},
) {
  return vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = new URL(String(input));
    if (url.pathname === "/api/admin/overview") return json(overview);
    if (url.pathname === "/api/admin/publication-preview/papers") return json(preview);
    if (url.pathname === "/api/admin/capabilities") return json(humanCapabilities);
    if (url.pathname === "/api/admin/ingestion-sync") return json(sync);
    if (url.pathname === "/api/admin/review-events") return json({ total: 0, limit: 50, offset: 0, items: [] });
    if (url.pathname === "/api/admin/review-queue") {
      requestedQueues.push(url.href);
      if (requestedQueues.length > 20) throw new Error("Review queue request loop detected in test fixture");
      const type = url.searchParams.get("item_type") as keyof typeof itemsByType | null;
      const items = type ? [...itemsByType[type]] : [author];
      return json({ total: options.total ?? items.length, limit: 50, offset: Number(url.searchParams.get("offset") ?? 0), items });
    }
    if (init?.method === "PATCH") {
      requests.push({ path: url.pathname, body: JSON.parse(String(init.body)) });
      return json({ review_event: {}, author: {}, author_alias: {}, topic: {}, paper_topic: {}, author_topic: {} });
    }
    return json({ detail: `Unhandled ${url.pathname}` }, { status: 404 });
  });
}

function queueItem(itemType: string, itemId: string, title: string, details: Record<string, unknown>) {
  return {
    item_type: itemType,
    item_id: itemId,
    title,
    label: title,
    status: "needs_review",
    grounding_status: null,
    warnings: Array.isArray(details.approval_blockers) ? details.approval_blockers : [],
    created_at: "2026-07-20T12:00:00Z",
    updated_at: "2026-07-20T12:00:00Z",
    frontend_link: "admin:governance",
    details,
  };
}
