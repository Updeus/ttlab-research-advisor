import type {
  AdminOverview,
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
  SearchDiagnostics,
  SearchMode,
  SearchResponse,
  Stats,
  TopicDetail,
} from "../types/paper";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

async function patchJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function fetchPapers(): Promise<Paper[]> {
  return getJson<Paper[]>("/api/papers");
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

export function searchChunks(query: string, mode: SearchMode, limit: number): Promise<SearchResponse> {
  const params = new URLSearchParams({ q: query, mode, limit: String(limit) });
  return getJson<SearchResponse>(`/api/search?${params.toString()}`);
}

export function fetchSearchDiagnostics(): Promise<SearchDiagnostics> {
  return getJson<SearchDiagnostics>("/api/search/diagnostics");
}

export async function askTtlab(request: AskRequest): Promise<AskResponse> {
  const response = await fetch(`${API_BASE}/api/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json() as Promise<AskResponse>;
}

export function fetchAskDiagnostics(): Promise<AskDiagnostics> {
  return getJson<AskDiagnostics>("/api/ask/diagnostics");
}

export async function recommendExtensions(request: ExtensionFinderRequest): Promise<ExtensionFinderResponse> {
  const response = await fetch(`${API_BASE}/api/recommendations/extensions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json() as Promise<ExtensionFinderResponse>;
}

export function fetchExtensionDiagnostics(): Promise<ExtensionDiagnostics> {
  return getJson<ExtensionDiagnostics>("/api/recommendations/extensions/diagnostics");
}

export function fetchPaperArtifacts(paperId: string): Promise<PaperArtifact[]> {
  return getJson<PaperArtifact[]>(`/api/papers/${paperId}/artifacts`);
}

export async function generatePaperArtifacts(paperId: string): Promise<GenerateArtifactsResponse> {
  const response = await fetch(`${API_BASE}/api/papers/${paperId}/artifacts/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      artifact_types: ["paper_intelligence_bundle", "podcast_script"],
      provider: "auto",
      max_chunks: 12,
      overwrite: false,
    }),
  });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json() as Promise<GenerateArtifactsResponse>;
}

export function fetchAdminOverview(): Promise<AdminOverview> {
  return getJson<AdminOverview>("/api/admin/overview");
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
  return getJson<ReviewQueueResponse>(`/api/admin/review-queue${query ? `?${query}` : ""}`);
}

export function fetchReviewEvents(params: { item_type?: string; item_id?: string; limit?: number } = {}): Promise<ReviewEvent[]> {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") {
      search.set(key, String(value));
    }
  });
  const query = search.toString();
  return getJson<ReviewEvent[]>(`/api/admin/review-events${query ? `?${query}` : ""}`);
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
  body: { review_status: ReviewStatus; reviewer_notes?: string; corrected_text?: string },
): Promise<{ artifact: Record<string, unknown>; review_event: ReviewEvent }> {
  return patchJson<{ artifact: Record<string, unknown>; review_event: ReviewEvent }>(`/api/admin/artifacts/${artifactId}/review`, body);
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

export function fetchEvaluationDashboard(): Promise<EvaluationDashboard> {
  return getJson<EvaluationDashboard>("/api/evaluation/dashboard");
}

export function fetchExplorerOverview(): Promise<ExplorerOverview> {
  return getJson<ExplorerOverview>("/api/explorer/overview");
}

export function fetchTopics(params: { q?: string; min_papers?: number; limit?: number; offset?: number } = {}): Promise<PaginatedTopics> {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") {
      search.set(key, String(value));
    }
  });
  const query = search.toString();
  return getJson<PaginatedTopics>(`/api/topics${query ? `?${query}` : ""}`);
}

export function fetchTopicDetail(topicId: string): Promise<TopicDetail> {
  return getJson<TopicDetail>(`/api/topics/${encodeURIComponent(topicId)}`);
}

export function fetchAuthors(params: { q?: string; topic?: string; limit?: number; offset?: number } = {}): Promise<PaginatedAuthors> {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") {
      search.set(key, String(value));
    }
  });
  const query = search.toString();
  return getJson<PaginatedAuthors>(`/api/authors${query ? `?${query}` : ""}`);
}

export function fetchAuthorDetail(authorId: number): Promise<AuthorDetail> {
  return getJson<AuthorDetail>(`/api/authors/${authorId}`);
}

export function fetchRelatedPapers(paperId: string, limit = 5): Promise<RelatedPaper[]> {
  return getJson<RelatedPaper[]>(`/api/papers/${paperId}/related?limit=${limit}`);
}
