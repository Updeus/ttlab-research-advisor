export type ReviewStatus = "needs_review" | "reviewed" | "approved" | "rejected" | "needs_reprocess";

export type Paper = {
  paper_id: string;
  title: string;
  authors: string[];
  year: number | null;
  publication_date_raw: string | null;
  venue: string | null;
  abstract: string | null;
  source_url: string | null;
  post_url: string | null;
  pdf_url: string | null;
  local_pdf_path: string | null;
  topics: string[];
  ingestion_status: string;
  pdf_text_status: string;
  extracted_json_path: string | null;
  extracted_text_path: string | null;
  page_count: number | null;
  total_char_count: number;
  total_word_count: number;
  pages_with_text: number;
  pages_without_text: number;
  possible_scanned_pdf: boolean;
  chunk_count: number;
  review_status: ReviewStatus | string;
  reviewer_notes: string | null;
  reviewed_at: string | null;
  reviewed_by: string | null;
  created_at: string;
  updated_at: string;
};

export type Stats = {
  papers: number;
  with_pdf_url: number;
  downloaded_pdfs: number;
  extracted_pdfs: number;
  extraction_failed: number;
  no_text_pdfs: number;
  missing_pdf: number;
  total_chunks: number;
  topic_count: number;
  author_count: number;
  paper_topic_links: number;
  author_topic_links: number;
  papers_with_topics: number;
  authors_with_topics: number;
  searchable_papers: number;
  searchable_chunks: number;
  keyword_indexed_chunks: number;
  semantic_indexed_chunks: number;
  total_ask_answers: number;
  grounded_answers: number;
  partial_answers: number;
  unsupported_answers: number;
  default_ask_provider: string;
  total_extension_recommendation_runs: number;
  total_extension_ideas: number;
  grounded_extension_runs: number;
  partial_extension_runs: number;
  unsupported_extension_runs: number;
  total_paper_artifacts: number;
  papers_with_artifacts: number;
  podcast_scripts_generated: number;
  artifacts_needing_review: number;
  admin_review_queue_count: number;
  papers_needing_review: number;
  answers_needing_review: number;
  recommendations_needing_review: number;
  total_review_events: number;
  latest_review_event_at: string | null;
  evaluation_files_present: Record<string, boolean>;
  evaluation_last_run_at: string | null;
  top_topics: [string, number][];
  recent_papers: Paper[];
  evaluation_status: string;
};

export type ExtractionDiagnostics = {
  paper_id: string;
  pdf_url: string | null;
  local_pdf_path: string | null;
  pdf_text_status: string;
  page_count: number | null;
  total_char_count: number;
  total_word_count: number;
  pages_with_text: number;
  pages_without_text: number;
  possible_scanned_pdf: boolean;
  warnings: string[];
  extraction_error: string | null;
  extracted_json_path: string | null;
  extracted_text_path: string | null;
  chunk_count: number;
};

export type PaperChunk = {
  chunk_id: string;
  paper_id: string;
  chunk_index: number;
  page_start: number | null;
  page_end: number | null;
  section: string | null;
  snippet: string;
  text: string;
  char_count: number;
  word_count: number;
  token_count_estimate: number | null;
  source_hash: string | null;
};

export type SearchMode = "keyword" | "semantic" | "hybrid";

export type SearchResult = {
  rank: number;
  paper_id: string;
  paper_title: string;
  authors: string[];
  year: number | null;
  chunk_id: string;
  section: string | null;
  page_start: number | null;
  page_end: number | null;
  snippet: string;
  scores: {
    keyword: number;
    semantic: number;
    combined: number;
  };
  source: {
    pdf_url: string | null;
    post_url: string | null;
    local_pdf_path: string | null;
  };
};

export type SearchResponse = {
  query: string;
  mode: SearchMode;
  result_count: number;
  results: SearchResult[];
  warnings: string[];
};

export type SearchDiagnostics = {
  searchable_chunks: number;
  searchable_papers: number;
  chunks_indexed_for_keyword_search: number;
  chunks_indexed_for_semantic_search: number;
  embedding_provider: string;
  embedding_dimensions: number;
  index_path: string;
  index_status: string;
  last_indexed_timestamp: string | null;
};

export type AskRequest = {
  question: string;
  mode: SearchMode;
  top_k: number;
  audience: string;
  max_words: number;
  provider: string;
};

export type AskCitation = {
  paper_id: string;
  title: string;
  authors: string[];
  year: number | null;
  chunk_id: string;
  section: string | null;
  page_start: number | null;
  page_end: number | null;
  snippet: string;
  score: number;
  source_url: string | null;
  pdf_url: string | null;
};

export type AskRetrievedChunk = {
  chunk_id: string;
  paper_id: string;
  title: string;
  authors: string[];
  year: number | null;
  page_start: number | null;
  page_end: number | null;
  section: string | null;
  snippet: string;
  scores: {
    keyword?: number;
    semantic?: number;
    combined?: number;
  };
};

export type AskResponse = {
  answer_id: string;
  question: string;
  answer: string;
  grounding_status: "grounded" | "partial" | "unsupported";
  provider: string;
  model: string;
  retrieval_mode: SearchMode;
  top_k: number;
  citations: AskCitation[];
  retrieved_chunks: AskRetrievedChunk[];
  warnings: string[];
  unsupported_claims: string[];
  review_status: ReviewStatus;
  reviewer_notes: string | null;
  reviewed_at: string | null;
  reviewed_by: string | null;
  citation_correct: boolean | null;
  answer_faithfulness_score: number | null;
  usefulness_score: number | null;
  created_at: string;
};

export type AskDiagnostics = {
  total_stored_answers: number;
  grounded_answers: number;
  partial_answers: number;
  unsupported_answers: number;
  default_provider: string;
  external_provider_available: boolean;
  searchable_chunks: number;
  semantic_indexed_chunks: number;
  last_answer_timestamp: string | null;
};

export type ExtensionFinderRequest = {
  interests: string;
  skills: string[];
  available_time: "2 weeks" | "1 month" | "semester";
  project_type:
    | "software prototype"
    | "data analysis"
    | "ML experiment"
    | "literature/systematic review support"
    | "dashboard/visualization"
    | "other";
  data_constraints: string;
  preferred_difficulty: "easy" | "medium" | "hard";
  preferred_topics: string[];
  avoid_topics: string[];
  top_k: number;
  retrieval_mode: SearchMode;
  provider: string;
};

export type ExtensionSourceFact = {
  claim: string;
  chunk_id: string;
  page_start: number | null;
  page_end: number | null;
  snippet: string;
};

export type ExtensionCitation = {
  paper_id: string;
  title: string;
  chunk_id: string;
  section: string | null;
  page_start: number | null;
  page_end: number | null;
  snippet: string;
  score: number;
  source_url: string | null;
  pdf_url: string | null;
};

export type ExtensionRecommendation = {
  rank: number;
  paper_id: string;
  paper_title: string;
  authors: string[];
  year: number | null;
  fit_score: number;
  score_breakdown: Record<string, number>;
  paper_focus: string;
  source_supported_facts: ExtensionSourceFact[];
  identified_gap: {
    text: string;
    support_status: "explicit_in_paper" | "inferred_from_paper" | "not_found";
    source_chunk_ids: string[];
  };
  extension_title: string;
  extension_summary: string;
  why_it_fits_student: string;
  mvp_scope: string;
  stretch_goals: string[];
  required_skills: string[];
  skills_gap: string[];
  data_required: string;
  data_availability: "public" | "needs_supervisor" | "private" | "synthetic" | "unknown";
  evaluation_plan: string;
  difficulty: "easy" | "medium" | "hard";
  risk_level: "low" | "medium" | "high";
  implementation_time: "2 weeks" | "1 month" | "semester" | "unknown";
  related_papers: {
    paper_id: string;
    title: string;
    reason: string;
  }[];
  potential_researcher_fit: {
    name: string;
    reason: string;
  }[];
  citations: ExtensionCitation[];
  warnings: string[];
};

export type ExtensionFinderResponse = {
  recommendation_id: string;
  request: ExtensionFinderRequest;
  grounding_status: "grounded" | "partial" | "unsupported";
  recommendations: ExtensionRecommendation[];
  warnings: string[];
  provider: string;
  model: string;
  retrieval_mode: SearchMode;
  top_k: number;
  review_status: ReviewStatus;
  reviewer_notes: string | null;
  reviewed_at: string | null;
  reviewed_by: string | null;
  corrected_recommendations_json: Record<string, unknown>;
  created_at: string;
};

export type ExtensionDiagnostics = {
  total_recommendation_runs: number;
  total_recommendations_generated: number;
  grounded_runs: number;
  partial_runs: number;
  unsupported_runs: number;
  searchable_chunks: number;
  searchable_papers: number;
  default_provider: string;
  last_recommendation_timestamp: string | null;
};

export type ArtifactCitation = {
  paper_id: string;
  title: string;
  chunk_id: string;
  section: string | null;
  page_start: number | null;
  page_end: number | null;
  snippet: string;
};

export type ArtifactSection = {
  text?: string;
  support_status?: "explicit" | "inferred" | "not_found" | "suggested_by_system";
  basis?: "explicit" | "inferred" | "not_found" | "suggested_by_system" | string;
  citations?: ArtifactCitation[];
  skills?: string[];
  items?: ExtensionArtifactItem[];
};

export type ExtensionArtifactItem = {
  title: string;
  summary: string;
  support_status: "suggested_by_system" | "explicit" | "inferred" | "not_found";
  source_basis: string[];
  citations: ArtifactCitation[];
};

export type PaperIntelligenceBundle = {
  paper_id: string;
  paper_title: string;
  authors: string[];
  year: number | null;
  generated_notice: string;
  public_summary: ArtifactSection;
  technical_summary: ArtifactSection;
  contribution: ArtifactSection;
  methods: ArtifactSection;
  limitations: ArtifactSection;
  future_work: ArtifactSection;
  possible_extensions: ExtensionArtifactItem[];
  required_skills: ArtifactSection;
  evaluation_plan: ArtifactSection;
  warnings: string[];
  review_status: ReviewStatus;
};

export type PodcastScriptArtifact = {
  episode_title: string;
  short_description: string;
  audience: string;
  duration_target: "3-5 minutes";
  speakers: string[];
  script: {
    speaker: string;
    text: string;
  }[];
  cited_source_papers: {
    paper_id: string;
    title: string;
  }[];
  citations: ArtifactCitation[];
  warnings: string[];
  review_status: ReviewStatus;
};

export type PaperArtifact = {
  artifact_id: string;
  paper_id: string;
  artifact_type: string;
  generated_json: PaperIntelligenceBundle | PodcastScriptArtifact | ArtifactSection | Record<string, unknown>;
  generated_text: string;
  source_chunk_ids: string[];
  citations: ArtifactCitation[];
  provider: string;
  model: string;
  generation_status: "generated" | "failed" | "insufficient_sources";
  grounding_status: "grounded" | "partial" | "unsupported";
  review_status: ReviewStatus;
  reviewer_notes: string | null;
  reviewed_at: string | null;
  reviewed_by: string | null;
  corrected_text: string | null;
  corrected_json: Record<string, unknown>;
  warnings: string[];
  created_at: string;
  updated_at: string;
};

export type GenerateArtifactsResponse = {
  paper_id: string;
  paper_title: string;
  artifacts: PaperArtifact[];
  grounding_status: "grounded" | "partial" | "unsupported";
  review_status: ReviewStatus;
  citations: ArtifactCitation[];
  warnings: string[];
  saved_json_path: string | null;
};

export type ReviewEvent = {
  review_event_id: string;
  item_type: string;
  item_id: string;
  action: string;
  previous_status: string | null;
  new_status: string | null;
  reviewer_name: string;
  reviewer_notes: string | null;
  diff: Record<string, unknown>;
  created_at: string;
};

export type AdminOverview = {
  papers_total: number;
  papers_needing_metadata_review: number;
  papers_missing_pdfs: number;
  papers_with_extraction_failures: number;
  possible_scanned_pdfs: number;
  total_chunks: number;
  rag_answers: Record<string, number>;
  rag_answers_by_grounding: Record<string, number>;
  thesis_recommendations: Record<string, number>;
  thesis_recommendations_by_grounding: Record<string, number>;
  paper_artifacts: Record<string, number>;
  paper_artifacts_by_grounding: Record<string, number>;
  paper_artifacts_by_type: Record<string, number>;
  artifacts_needing_review: number;
  total_review_events: number;
  recent_review_events: ReviewEvent[];
};

export type ReviewQueueItem = {
  item_type: "paper" | "rag_answer" | "thesis_recommendation" | "paper_artifact";
  item_id: string;
  title: string;
  label: string;
  status: ReviewStatus | string;
  grounding_status: "grounded" | "partial" | "unsupported" | null;
  warnings: string[];
  created_at: string | null;
  updated_at: string | null;
  frontend_link: string;
  details: Record<string, unknown>;
};

export type ReviewQueueResponse = {
  total: number;
  limit: number;
  offset: number;
  items: ReviewQueueItem[];
};

export type EvaluationSectionStatus = {
  status: "not_run" | "available" | "invalid";
  result_file_exists: boolean;
  path: string;
  last_run_timestamp: string | null;
  [key: string]: unknown;
};

export type EvaluationDashboard = {
  retrieval: EvaluationSectionStatus & {
    question_count: number;
    recall_at_3: number | null;
    recall_at_5: number | null;
    mrr: number | null;
  };
  qa: EvaluationSectionStatus & {
    question_count: number;
    answer_count: number;
    cited_gold_paper_count: number;
    citation_count: number;
    grounding_counts: Record<string, number>;
  };
  extension: EvaluationSectionStatus & {
    case_count: number;
    recommendation_count: number;
    citation_coverage: number | null;
    grounding_counts: Record<string, number>;
    warnings_count: number;
  };
  artifact: EvaluationSectionStatus & {
    case_count: number;
    artifact_count: number;
    citation_coverage: number | null;
    grounding_counts: Record<string, number>;
    warnings_count: number;
    sections_with_explicit_support: number;
    sections_inferred: number;
    sections_not_found: number;
  };
  human_review_templates: Record<string, boolean>;
  overall_quality: Record<string, number>;
  result_files: Record<string, { path: string; exists: boolean; last_modified: string | null }>;
};

export type PaperSummary = {
  paper_id: string;
  title: string;
  authors: string[];
  year: number | null;
  venue: string | null;
  source_url: string | null;
  pdf_url: string | null;
};

export type AuthorSummary = {
  author_id: number;
  name: string;
  paper_count: number;
  score?: number;
  top_topics?: AuthorTopicSummary[];
  recent_papers?: PaperSummary[];
  coauthor_count?: number;
  review_status?: string;
};

export type AuthorTopicSummary = {
  topic_id: string;
  name: string;
  paper_count: number;
  score: number;
  evidence?: ExplorerEvidence[];
};

export type TopicSummary = {
  topic_id: string;
  name: string;
  normalized_name: string;
  description: string | null;
  paper_count: number;
  author_count: number;
  top_authors: AuthorSummary[];
  sample_papers: PaperSummary[];
  review_status: string;
};

export type TopicDetail = TopicSummary & {
  papers: (PaperSummary & { score: number; evidence: ExplorerEvidence[] })[];
  authors: AuthorSummary[];
  related_topics: {
    topic_id: string;
    name: string;
    shared_paper_count: number;
  }[];
};

export type AuthorDetail = AuthorSummary & {
  papers: PaperSummary[];
  topics: AuthorTopicSummary[];
  coauthors: { name: string; paper_count: number }[];
  venues: string[];
  generated_artifacts_count: number;
  potential_expertise_summary: string;
  source_basis: string;
};

export type ExplorerEvidence = {
  source?: string;
  field?: string;
  text?: string;
  chunk_id?: string | null;
  artifact_id?: string | null;
  score?: number;
  paper_id?: string;
  paper_title?: string;
};

export type ExplorerOverview = {
  topic_count: number;
  author_count: number;
  paper_count: number;
  linked_paper_topics: number;
  linked_author_topics: number;
  top_topics: TopicSummary[];
  top_authors: AuthorSummary[];
  recent_papers: PaperSummary[];
  explorer_index_status: "ready" | "empty" | string;
};

export type PaginatedTopics = {
  total: number;
  limit: number;
  offset: number;
  items: TopicSummary[];
};

export type PaginatedAuthors = {
  total: number;
  limit: number;
  offset: number;
  items: AuthorSummary[];
};

export type RelatedPaper = PaperSummary & {
  score: number;
  reason: string;
  shared_topics: string[];
  shared_authors: string[];
  source_basis: string[];
};
