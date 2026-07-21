import type {
  AdminOverview,
  AdminPublicationPreview,
  ActorCapabilities,
  AskDiagnostics,
  AskRequest,
  AskResponse,
  EvaluationDashboard,
  ExplorerOverview,
  ExtensionDiagnostics,
  ExtensionFinderRequest,
  ExtensionFinderResponse,
  ExtractionDiagnostics,
  GenerateArtifactsResponse,
  IngestionSyncStatus,
  LocalLlmStatus,
  Paper,
  PaperArtifact,
  PaperChunk,
  PaginatedAuthors,
  PaginatedTopics,
  AuthorDetail,
  RelatedPaper,
  ReviewQueueResponse,
  ReviewStatus,
  ReviewEvent,
  ReviewEventsResponse,
  SearchDiagnostics,
  SearchMode,
  SearchResponse,
  Stats,
  TopicDetail,
  ServiceStatus,
} from "../types/paper";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";

let reviewerToken = "";
const topicDetailInFlight = new Map<string, Promise<TopicDetail>>();
const authorDetailInFlight = new Map<string, Promise<AuthorDetail>>();

export class ApiError extends Error {
  status: number;
  path: string;

  constructor(path: string, status: number, detail?: string) {
    super(detail ? `${detail} (${status})` : `Request failed: ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.path = path;
  }
}

type RequestOptions = {
  authenticated?: boolean;
  signal?: AbortSignal;
};

export function setReviewerToken(token: string) {
  reviewerToken = token.trim();
}

export function hasReviewerToken(): boolean {
  return Boolean(reviewerToken);
}

export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException
    ? error.name === "AbortError"
    : error instanceof Error && error.name === "AbortError";
}

function authHeaders(): Record<string, string> {
  return reviewerToken ? { Authorization: `Bearer ${reviewerToken}` } : {};
}

function requestOnce<T>(requests: Map<string, Promise<T>>, key: string, requestFactory: () => Promise<T>): Promise<T> {
  const inFlight = requests.get(key);
  if (inFlight) return inFlight;
  const request = requestFactory();
  requests.set(key, request);
  const clear = () => {
    if (requests.get(key) === request) requests.delete(key);
  };
  request.then(clear, clear);
  return request;
}

async function parseError(response: Response, path: string): Promise<ApiError> {
  let detail = "";
  try {
    const payload = await response.json() as { detail?: unknown };
    detail = formatErrorDetail(payload.detail);
  } catch {
    // Preserve the status when an upstream proxy returns a non-JSON error.
  }
  return new ApiError(path, response.status, detail);
}

function formatErrorDetail(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const detail = value as { code?: unknown; message?: unknown; approval_blockers?: unknown };
    if (detail.code === "approval_blocked" && Array.isArray(detail.approval_blockers)) {
      const blockers = detail.approval_blockers.filter((item): item is string => typeof item === "string");
      return blockers.length ? `Approval blocked: ${blockers.join(", ")}` : "Approval blocked by record dependencies";
    }
    return typeof detail.message === "string" ? detail.message : "";
  }
  if (!Array.isArray(value)) {
    return "";
  }
  return value
    .map((item) => {
      if (!item || typeof item !== "object") {
        return "";
      }
      const error = item as { loc?: unknown; msg?: unknown };
      const message = typeof error.msg === "string" ? error.msg : "Invalid value";
      const location = Array.isArray(error.loc)
        ? error.loc.filter((part) => part !== "body").map(String).join(".")
        : "";
      return location ? `${location}: ${message}` : message;
    })
    .filter(Boolean)
    .join("; ");
}

async function getJson<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: options.authenticated ? authHeaders() : undefined,
    signal: options.signal,
  });
  if (!response.ok) {
    throw await parseError(response, path);
  }
  return response.json() as Promise<T>;
}

async function patchJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw await parseError(response, path);
  }
  return response.json() as Promise<T>;
}

async function postJson<T>(path: string, body: unknown = {}, options: RequestOptions = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(options.authenticated ? authHeaders() : {}) },
    body: JSON.stringify(body),
    signal: options.signal,
  });
  if (!response.ok) {
    throw await parseError(response, path);
  }
  return response.json() as Promise<T>;
}

export function fetchPapers(signal?: AbortSignal): Promise<Paper[]> {
  return getJson<Paper[]>("/api/papers", { signal });
}

export function fetchPaper(paperId: string, signal?: AbortSignal): Promise<Paper> {
  return getJson<Paper>(`/api/papers/${encodeURIComponent(paperId)}`, { signal });
}

export function fetchServiceStatus(): Promise<ServiceStatus> {
  return getJson<ServiceStatus>("");
}

export function fetchStats(): Promise<Stats> {
  return getJson<Stats>("/api/stats");
}

export function fetchExtraction(paperId: string): Promise<ExtractionDiagnostics> {
  return getJson<ExtractionDiagnostics>(`/api/papers/${paperId}/extraction`);
}

export function fetchPaperChunks(paperId: string): Promise<PaperChunk[]> {
  return getJson<PaperChunk[]>(`/api/papers/${paperId}/chunks`);
}

export function searchChunks(query: string, mode: SearchMode, limit: number, signal?: AbortSignal): Promise<SearchResponse> {
  const params = new URLSearchParams({ q: query, mode, limit: String(limit) });
  return getJson<SearchResponse>(`/api/search?${params.toString()}`, { signal });
}

export function fetchSearchDiagnostics(): Promise<SearchDiagnostics> {
  return getJson<SearchDiagnostics>("/api/search/diagnostics");
}

export async function askTtlab(request: AskRequest, signal?: AbortSignal): Promise<AskResponse> {
  const response = await fetch(`${API_BASE}/api/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
    signal,
  });
  if (!response.ok) {
    throw await parseError(response, "/api/ask");
  }
  return response.json() as Promise<AskResponse>;
}

export function fetchAskDiagnostics(): Promise<AskDiagnostics> {
  return getJson<AskDiagnostics>("/api/ask/diagnostics");
}

export function fetchLocalLlms(): Promise<LocalLlmStatus> {
  return getJson<LocalLlmStatus>("/api/llms/local");
}

export function fetchLatestLlmBenchmark(): Promise<Record<string, unknown>> {
  return getJson<Record<string, unknown>>("/api/llms/benchmark/latest");
}

export async function recommendExtensions(request: ExtensionFinderRequest, signal?: AbortSignal): Promise<ExtensionFinderResponse> {
  const response = await fetch(`${API_BASE}/api/recommendations/extensions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
    signal,
  });
  if (!response.ok) {
    throw await parseError(response, "/api/recommendations/extensions");
  }
  return response.json() as Promise<ExtensionFinderResponse>;
}

export function fetchExtensionDiagnostics(): Promise<ExtensionDiagnostics> {
  return getJson<ExtensionDiagnostics>("/api/recommendations/extensions/diagnostics");
}

export function fetchPaperArtifacts(paperId: string): Promise<PaperArtifact[]> {
  return getJson<PaperArtifact[]>(`/api/papers/${paperId}/artifacts`);
}

export async function generatePaperArtifacts(paperId: string, overwrite = false): Promise<GenerateArtifactsResponse> {
  const response = await fetch(`${API_BASE}/api/papers/${paperId}/artifacts/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({
      artifact_types: ["paper_intelligence_bundle", "podcast_script"],
      provider: "auto",
      max_chunks: 12,
      overwrite,
    }),
  });
  if (!response.ok) {
    throw await parseError(response, `/api/papers/${paperId}/artifacts/generate`);
  }
  return response.json() as Promise<GenerateArtifactsResponse>;
}

export function fetchAdminOverview(): Promise<AdminOverview> {
  return getJson<AdminOverview>("/api/admin/overview", { authenticated: true });
}

export function fetchAdminPublicationPreview(): Promise<AdminPublicationPreview> {
  return getJson<AdminPublicationPreview>("/api/admin/publication-preview/papers", { authenticated: true });
}

export function decidePaperPublication(
  paperId: string,
  body: {
    publication_status: "pending_review" | "published" | "hidden";
    rights_status: "unknown" | "cleared" | "restricted";
    public_access_level: "hidden" | "metadata_only" | "searchable";
    reviewer_notes?: string;
  },
): Promise<{ paper: Record<string, unknown>; review_event: ReviewEvent | null }> {
  return patchJson<{ paper: Record<string, unknown>; review_event: ReviewEvent | null }>(
    `/api/admin/papers/${encodeURIComponent(paperId)}/publication`,
    body,
  );
}

export function fetchActorCapabilities(): Promise<ActorCapabilities> {
  return getJson<ActorCapabilities>("/api/admin/capabilities", { authenticated: true });
}

export function fetchIngestionSyncStatus(): Promise<IngestionSyncStatus> {
  return getJson<IngestionSyncStatus>("/api/admin/ingestion-sync", { authenticated: true });
}

export function requestIngestionSync(): Promise<{
  accepted: boolean;
  message: string;
  sync: IngestionSyncStatus;
}> {
  return postJson("/api/admin/ingestion-sync/request", {}, { authenticated: true });
}

export function fetchReviewQueue(params: {
  item_type?: string;
  review_status?: string;
  grounding_status?: string;
  limit?: number;
  offset?: number;
}): Promise<ReviewQueueResponse> {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") {
      search.set(key, String(value));
    }
  });
  const query = search.toString();
  return getJson<ReviewQueueResponse>(`/api/admin/review-queue${query ? `?${query}` : ""}`, { authenticated: true });
}

export function fetchReviewEvents(params: { item_type?: string; item_id?: string; limit?: number; offset?: number } = {}): Promise<ReviewEventsResponse> {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") {
      search.set(key, String(value));
    }
  });
  const query = search.toString();
  return getJson<ReviewEventsResponse>(`/api/admin/review-events${query ? `?${query}` : ""}`, { authenticated: true });
}

export function patchAdminPaper(
  paperId: string,
  body: Partial<
    Pick<
      Paper,
      | "title"
      | "authors"
      | "year"
      | "publication_date_raw"
      | "venue"
      | "topics"
      | "source_url"
      | "pdf_url"
      | "abstract"
      | "review_status"
      | "reviewer_notes"
    >
  >,
): Promise<{ paper: Paper; review_event: ReviewEvent }> {
  return patchJson<{ paper: Paper; review_event: ReviewEvent }>(`/api/admin/papers/${paperId}`, body);
}

export function reviewArtifact(
  artifactId: string,
  body: { review_status: ReviewStatus; reviewer_notes?: string },
): Promise<{ artifact: Record<string, unknown>; review_event: ReviewEvent }> {
  return patchJson<{ artifact: Record<string, unknown>; review_event: ReviewEvent }>(`/api/admin/artifacts/${artifactId}/review`, body);
}

export function saveArtifactCorrection(
  artifactId: string,
  body: { corrected_text?: string; corrected_json?: Record<string, unknown>; reviewer_notes?: string },
): Promise<{ artifact: Record<string, unknown>; review_event: ReviewEvent | null }> {
  return patchJson<{ artifact: Record<string, unknown>; review_event: ReviewEvent | null }>(`/api/admin/artifacts/${artifactId}/correction`, body);
}

export function reviewRecommendation(
  recommendationId: string,
  body: { review_status: ReviewStatus; reviewer_notes?: string },
): Promise<{ recommendation: Record<string, unknown>; review_event: ReviewEvent }> {
  return patchJson<{ recommendation: Record<string, unknown>; review_event: ReviewEvent }>(
    `/api/admin/recommendations/${recommendationId}/review`,
    body,
  );
}

export function saveRecommendationCorrection(
  recommendationId: string,
  body: { corrected_recommendations_json: Record<string, unknown> | Record<string, unknown>[]; reviewer_notes?: string },
): Promise<{ recommendation: Record<string, unknown>; review_event: ReviewEvent | null }> {
  return patchJson<{ recommendation: Record<string, unknown>; review_event: ReviewEvent | null }>(
    `/api/admin/recommendations/${encodeURIComponent(recommendationId)}/correction`,
    body,
  );
}

export function reviewAnswer(
  answerId: string,
  body: {
    review_status: ReviewStatus;
    reviewer_notes?: string;
    citation_correct?: boolean | null;
    answer_faithfulness_score?: number | null;
    usefulness_score?: number | null;
  },
): Promise<{ answer: Record<string, unknown>; review_event: ReviewEvent }> {
  return patchJson<{ answer: Record<string, unknown>; review_event: ReviewEvent }>(`/api/admin/answers/${answerId}/review`, body);
}

export function reviewExtraction(
  paperId: string,
  body: { review_status: ReviewStatus; reviewer_notes?: string },
): Promise<{ paper: Paper; review_event: ReviewEvent }> {
  return patchJson<{ paper: Paper; review_event: ReviewEvent }>(`/api/admin/extraction/${paperId}/review`, body);
}

export type GraphReviewItemType = "author" | "author_alias" | "topic" | "paper_topic" | "author_topic";

const graphReviewPaths: Record<GraphReviewItemType, string> = {
  author: "authors",
  author_alias: "author-aliases",
  topic: "topics",
  paper_topic: "paper-topics",
  author_topic: "author-topics",
};

export function reviewGraphRecord(
  itemType: GraphReviewItemType,
  itemId: string,
  body: { review_status: ReviewStatus; reviewer_notes?: string },
): Promise<{ review_event: ReviewEvent; [key: string]: unknown }> {
  const resource = graphReviewPaths[itemType];
  return patchJson<{ review_event: ReviewEvent; [key: string]: unknown }>(
    `/api/admin/${resource}/${encodeURIComponent(itemId)}/review`,
    body,
  );
}

export function saveGraphCorrection(
  itemType: GraphReviewItemType,
  itemId: string,
  body: Record<string, unknown>,
): Promise<{ review_event: ReviewEvent | null; [key: string]: unknown }> {
  const resource = graphReviewPaths[itemType];
  return patchJson<{ review_event: ReviewEvent | null; [key: string]: unknown }>(
    `/api/admin/${resource}/${encodeURIComponent(itemId)}/correction`,
    body,
  );
}

export function fetchEvaluationDashboard(): Promise<EvaluationDashboard> {
  return getJson<EvaluationDashboard>("/api/evaluation/dashboard");
}

export function fetchExplorerOverview(signal?: AbortSignal): Promise<ExplorerOverview> {
  return getJson<ExplorerOverview>("/api/explorer/overview", { signal });
}

export function fetchTopics(
  params: { q?: string; min_papers?: number; limit?: number; offset?: number } = {},
  signal?: AbortSignal,
): Promise<PaginatedTopics> {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") {
      search.set(key, String(value));
    }
  });
  const query = search.toString();
  return getJson<PaginatedTopics>(`/api/topics${query ? `?${query}` : ""}`, { signal });
}

export function fetchTopicDetail(topicId: string): Promise<TopicDetail> {
  return requestOnce(topicDetailInFlight, topicId, () => getJson<TopicDetail>(`/api/topics/${encodeURIComponent(topicId)}`));
}

export function fetchAuthors(
  params: { q?: string; topic?: string; limit?: number; offset?: number } = {},
  signal?: AbortSignal,
): Promise<PaginatedAuthors> {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") {
      search.set(key, String(value));
    }
  });
  const query = search.toString();
  return getJson<PaginatedAuthors>(`/api/authors${query ? `?${query}` : ""}`, { signal });
}

export function fetchAuthorDetail(authorId: number): Promise<AuthorDetail> {
  return requestOnce(authorDetailInFlight, String(authorId), () => getJson<AuthorDetail>(`/api/authors/${authorId}`));
}

export function fetchRelatedPapers(paperId: string, limit = 5): Promise<RelatedPaper[]> {
  return getJson<RelatedPaper[]>(`/api/papers/${paperId}/related?limit=${limit}`);
}
