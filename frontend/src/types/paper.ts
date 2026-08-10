export type ReviewStatus = "needs_review" | "ai_reviewed" | "reviewed" | "approved" | "rejected" | "needs_reprocess";

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
  doi: string | null;
  keywords: string[];
  topics: string[];
  ingestion_status: string;
  pdf_text_status: string;
  extraction_content_type: string;
  ocr_status: string;
  ocr_review_required: boolean;
  corpus_eligibility_status: string;
  corpus_exclusion_reason: string | null;
  publication_status: "pending_review" | "published" | "hidden";
  rights_status: "unknown" | "cleared" | "restricted";
  public_access_level: "hidden" | "metadata_only" | "searchable";
  pdf_title_match_status: string;
  page_count: number | null;
  chunk_count: number;
  review_status: ReviewStatus;
  demo_preview?: boolean;
  reviewed_at: string | null;
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
  pdf_unavailability_reasons: Record<string, number>;
  ocr_status_counts: Record<string, number>;
  extraction_content_type_counts: Record<string, number>;
  corpus_eligibility_status_counts: Record<string, number>;
  total_chunks: number;
  topic_count: number;
  author_count: number;
  paper_topic_links: number;
  author_topic_links: null;
  papers_with_topics: number;
  authors_with_topics: null;
  searchable_papers: number;
  searchable_chunks: number;
  eligible_chunks: number;
  raw_chunks: number;
  keyword_indexed_chunks: number;
  semantic_indexed_chunks: null;
  semantic_indexed_chunks_deprecated: string;
  feature_hashing_indexed_chunks: number;
  dense_indexed_chunks: number;
  keyword_index_status: string;
  feature_hashing_index_status: string;
  dense_index_status: string;
  index_health: {
    keyword: IndexDiagnostics;
    feature_hashing: IndexDiagnostics;
    dense: IndexDiagnostics;
  };
  default_ask_provider: string;
  evaluation_files_present: Record<string, boolean>;
  evaluation_last_run_at: string | null;
  top_topics: [string, number][];
  recent_papers: Paper[];
  evaluation_status: string;
  corpus_access_mode?: "approved_public_projection" | "unreviewed_local_demo_preview";
};

export type ExtractionDiagnostics = {
  paper_id: string;
  pdf_url: string | null;
  pdf_text_status: string;
  pdf_unavailability_reason: string | null;
  page_count: number | null;
  total_char_count: number;
  total_word_count: number;
  pages_with_text: number;
  pages_without_text: number;
  possible_scanned_pdf: boolean;
  extraction_content_type: string;
  ocr_status: string;
  ocr_provider: string | null;
  ocr_provider_version: string | null;
  ocr_pages_count: number;
  ocr_review_required: boolean;
  pdf_title_match_status: string;
  pdf_title_match_score: number | null;
  corpus_eligibility_status: string;
  corpus_exclusion_reason: string | null;
  warnings: string[];
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

export type SearchMode = "keyword" | "feature_hashing" | "dense" | "hybrid";

export type RetrieverConfig = {
  enable_query_expansion: boolean;
  enable_metadata_boost: boolean;
  enable_section_boost: boolean;
  enable_evidence_adjustment: boolean;
  enable_topic_adjustment: boolean;
  enable_diversity_penalty: boolean;
  keyword_weight: number;
  vector_weight: number;
  metadata_scale: number;
  section_scale: number;
  evidence_scale: number;
  topic_scale: number;
  diversity_scale: number;
  candidate_multiplier: number;
};

export type IndexDiagnostics = {
  status: string;
  indexed_chunks: number;
  public_eligible_chunks: number;
  projection_status: string;
  underlying_index_status: string;
  underlying_representation_valid: boolean;
  underlying_error_count: number;
  last_indexed_at: string | null;
  classification?: "lexical_feature_hashing";
};

export type SearchResult = {
  rank: number;
  paper_id: string;
  paper_title: string;
  authors: string[];
  year: number | null;
  venue: string | null;
  topics: string[];
  chunk_id: string;
  chunk_index: number | null;
  section: string | null;
  page_start: number | null;
  page_end: number | null;
  snippet: string;
  scores: {
    keyword: number;
    vector: number;
    vector_provider: string | null;
    metadata: number;
    section_boost: number;
    evidence_quality: number;
    topical_alignment: number;
    diversity_penalty: number;
    combined: number;
  };
  source: {
    pdf_url: string | null;
    post_url: string | null;
  };
};

export type SearchResponse = {
  query: string;
  expanded_query: string;
  query_expansions: string[];
  mode: SearchMode;
  result_count: number;
  results: SearchResult[];
  warnings: string[];
  vector_provider: string | null;
  retrieval_strategy: string;
  retriever_config: RetrieverConfig;
  retrieval_scope: "public" | "technical";
  demo_preview?: boolean;
};

export type SearchDiagnostics = {
  total_chunks: number;
  raw_chunks: null;
  eligible_chunks: number;
  searchable_chunks: number;
  searchable_papers: number;
  chunks_indexed_for_keyword_search: number;
  chunks_indexed_for_semantic_search: null;
  chunks_indexed_for_feature_hashing: number;
  chunks_indexed_for_dense_search: number;
  semantic_search_deprecation: string;
  embedding_provider: null;
  embedding_dimensions: null;
  index_status: string;
  last_indexed_timestamp: null;
  keyword: IndexDiagnostics;
  feature_hashing: IndexDiagnostics;
  dense: IndexDiagnostics;
  corpus_access_mode?: "approved_public_projection" | "unreviewed_local_demo_preview";
};

export type AskRequest = {
  question: string;
  mode: SearchMode;
  top_k: number;
  audience: string;
  max_words: number;
  provider: string;
  model?: string | null;
  paper_id?: string | null;
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
    keyword: number;
    vector: number;
    vector_provider: string | null;
    metadata: number;
    section_boost: number;
    evidence_quality: number;
    topical_alignment: number;
    diversity_penalty: number;
    combined: number;
  };
  source: {
    pdf_url: string | null;
    post_url: string | null;
  };
};

export type AskResponse = {
  answer_id: string;
  question: string;
  answer: string;
  grounding_status: "partial" | "unsupported";
  support_status: "support_unverified" | "unsupported";
  provider: string;
  model: string;
  retrieval_mode: SearchMode;
  top_k: number;
  paper_id: string | null;
  citations: AskCitation[];
  retrieved_chunks: AskRetrievedChunk[];
  retrieval_metadata: {
    expanded_query: string | null;
    query_expansions: string[];
    retrieval_strategy: string;
    retrieval_scope: "public" | "technical";
  };
  generation_metadata: Record<string, unknown>;
  answerability: {
    answerable: boolean;
    reason: string;
    query_terms: string[];
    matched_query_terms: string[];
    max_query_coverage: number;
    minimum_query_coverage?: number;
    relevant_chunk_ids: string[];
    warnings: string[];
  };
  claim_support: Array<{
    claim: string;
    classification: "support_unverified" | "unsupported";
    cited_chunk_ids: string[];
    supporting_chunk_ids: string[];
    citation_support: Array<{
      chunk_id: string;
      lexical_overlap: number;
      classification: "support_unverified" | "unsupported";
      entailment_verified: false;
    }>;
    lexical_overlap: number;
    entailment_verified: false;
  }>;
  runtime_provenance: Record<string, unknown>;
  source_text_delivery: "bounded_snippets_only";
  demo_preview?: boolean;
  warnings: string[];
  unsupported_claims: string[];
  created_at: string;
};

export type AskDiagnostics = {
  total_stored_answers: null;
  grounded_answers: null;
  partial_answers: null;
  unsupported_answers: null;
  default_provider: string;
  corpus_access_mode?: "approved_public_projection" | "unreviewed_local_demo_preview";
  history_counts_visibility: string;
  history_counts_observed: false;
  allowed_providers: string[];
  provider_matrix: Record<string, {
    enabled: boolean;
    effective_model?: string;
    configured_model?: string;
    configured_model_pinned?: boolean;
    pinned_model_count?: number;
    identity_scope: string;
  }>;
  external_provider_available: boolean;
  external_provider_availability_scope: string;
  scope: "public";
  searchable_chunks: number;
  raw_chunks: null;
  semantic_indexed_chunks: null;
  semantic_index_deprecation: string;
  last_answer_timestamp: null;
  keyword_index: IndexDiagnostics;
  feature_hashing_index: IndexDiagnostics;
  dense_index: IndexDiagnostics;
  dense_provider?: {
    state: "idle" | "warming" | "ready" | "unavailable";
    started_at: string | null;
    ready_at: string | null;
    elapsed_seconds: number | null;
  };
};

export type LocalLlmBenchmarkSummary = {
  runs: number;
  average_total_seconds: number;
  average_tokens_per_second: number;
  citation_compliance_rate: number;
  average_quality_score: number;
};

export type LocalLlmModel = {
  name: string;
  installed: boolean;
  usable?: boolean;
  digest_allowed?: boolean;
  source: string;
  size?: number | null;
  digest?: string | null;
  modified_at?: string | null;
  details?: Record<string, unknown>;
  color: "green" | "light_green" | "yellow" | "red" | string;
  quality_tier: string;
  rationale: string;
  benchmark?: LocalLlmBenchmarkSummary | null;
  is_default: boolean;
};

export type LocalLlmStatus = {
  available: boolean;
  generation_available?: boolean;
  base_url: string;
  default_model: string;
  model_count: number;
  models: LocalLlmModel[];
  candidate_pulls: {
    name: string;
    purpose: string;
    fit: string;
  }[];
  recommended_pulls: {
    name: string;
    purpose: string;
    fit: string;
  }[];
  benchmark: Record<string, unknown> | null;
  warnings: string[];
  model_policy?: "all_installed_local_models" | "pinned_digest_only";
};

export type GenerationStatus = {
  runtime_profile: "local" | "gcp";
  provider: string;
  display_name: string;
  configured: boolean;
  location?: string;
  model: string;
  model_selection_enabled: boolean;
  external_processing: boolean;
  privacy_notice: string;
};

export type IdeaChatMessage = {
  role: "user" | "assistant";
  content: string;
};

export type IdeaGenerationRequest = {
  message: string;
  history: IdeaChatMessage[];
};

export type GeneratedIdea = {
  title: string;
  research_question: string;
  summary: string;
  why_it_fits: string;
  mvp_scope: string;
  skills: string[];
  evaluation_plan: string;
  basis: "paper_informed" | "general_suggestion";
  source_chunk_ids: string[];
};

export type IdeaCitation = {
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

export type IdeaGenerationResponse = {
  message_id: string;
  reply: string;
  paper_match_status: "matched" | "none";
  ideas: GeneratedIdea[];
  citations: IdeaCitation[];
  provider: string;
  model: string;
  generation_metadata: Record<string, unknown>;
  runtime_provenance: Record<string, unknown>;
  warnings: string[];
  created_at: string;
  demo_preview?: boolean;
  corpus_access_mode?: "approved_public_projection" | "unreviewed_local_demo_preview";
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
  difficulty: "easy" | "medium" | "hard" | "unknown";
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
  review_status?: ReviewStatus;
  reviewer_notes?: string | null;
  reviewed_at?: string | null;
  reviewed_by?: string | null;
  corrected_recommendations_json?: Record<string, unknown>;
  created_at: string;
  demo_preview?: boolean;
  corpus_access_mode?: "approved_public_projection" | "unreviewed_local_demo_preview";
};

export type ExtensionDiagnostics = {
  total_recommendation_runs: number | null;
  total_recommendations_generated: number | null;
  grounded_runs: number | null;
  partial_runs: number | null;
  unsupported_runs: number | null;
  searchable_chunks: number;
  searchable_papers: number;
  default_provider: string;
  last_recommendation_timestamp: string | null;
  scope?: "public" | "technical_demo" | string;
  demo_preview?: boolean;
  corpus_access_mode?: "approved_public_projection" | "unreviewed_local_demo_preview";
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
  generated_json?: PaperIntelligenceBundle | PodcastScriptArtifact | ArtifactSection | Record<string, unknown>;
  generated_text?: string;
  effective_json?: PaperIntelligenceBundle | PodcastScriptArtifact | ArtifactSection | Record<string, unknown>;
  effective_text?: string;
  source_chunk_ids: string[];
  citations: ArtifactCitation[];
  provider?: string;
  model?: string;
  generation_status: "generated" | "failed" | "insufficient_sources";
  grounding_status: "grounded" | "partial" | "unsupported";
  review_status: ReviewStatus;
  reviewer_notes?: string | null;
  reviewed_at: string | null;
  reviewed_by?: string | null;
  corrected_text?: string | null;
  corrected_json?: Record<string, unknown> | null;
  provenance?: {
    provider: string;
    model: string;
    generated_at: string;
    approved_version: "generated" | "corrected" | string | null;
    correction_fields: string[];
  };
  warnings: string[];
  created_at?: string;
  updated_at?: string;
  demo_preview?: boolean;
  corpus_access_mode?: "approved_public_projection" | "unreviewed_local_demo_preview";
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
  reviewer_id?: string;
  reviewer_role?: string;
  reviewer_type?: string;
  request_id?: string;
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

export type AdminPublicationPreviewPaper = {
  paper_id: string;
  title: string;
  authors: string[];
  year: number | null;
  venue: string | null;
  topics: string[];
  source_url?: string | null;
  post_url?: string | null;
  pdf_text_status: string;
  corpus_eligibility_status: string;
  corpus_exclusion_reason: string | null;
  publication_status: "pending_review" | "published" | "hidden" | string;
  rights_status: "unknown" | "cleared" | "restricted" | string;
  public_access_level: "hidden" | "metadata_only" | "searchable" | string;
  review_status: ReviewStatus | string;
  pdf_unavailability_reason?: string | null;
  pdf_unavailability_detail?: string | null;
  possible_scanned_pdf?: boolean;
  extraction_content_type?: string;
  ocr_status?: string;
  ocr_provider?: string;
  ocr_provider_version?: string;
  ocr_pages_count?: number;
  ocr_review_required?: boolean;
  extraction_review_status?: ReviewStatus | string;
  extraction_reviewer_notes?: string | null;
  extraction_reviewed_by?: string | null;
  extraction_reviewer_type?: "human" | "ai" | "service" | string | null;
  extraction_reviewed_at?: string | null;
  pdf_title_match_status?: string;
  pdf_title_match_score?: number;
  reviewer_notes?: string | null;
};

export type AdminPublicationPreview = {
  surface: "local_review_preview";
  public: false;
  notice: string;
  items: AdminPublicationPreviewPaper[];
};

export type ActorCapabilities = {
  actor: {
    actor_id: string;
    role: "reviewer" | "admin";
    reviewer_type: "human" | "ai" | "service";
    local_demo_bypass: boolean;
  };
  capabilities: {
    review: boolean;
    save_corrections: boolean;
    approve_or_reject: boolean;
    set_publication_and_rights: boolean;
    trigger_ingestion: boolean;
  };
  allowed_review_transitions: Record<string, ReviewStatus[]>;
};

export type IngestionRun = {
  run_id: string;
  source: string;
  trigger: string;
  requested_by: string | null;
  status: "running" | "succeeded" | "failed" | "skipped" | string;
  discovered_count: number;
  created_count: number;
  updated_count: number;
  unchanged_count: number;
  downloaded_count: number;
  extracted_count: number;
  chunked_count: number;
  error_message: string | null;
  summary: Record<string, unknown>;
  started_at: string;
  finished_at: string | null;
};

export type IngestionSyncStatus = {
  source: "ttlab" | string;
  enabled: boolean;
  schedule: string;
  timezone: string;
  run_on_startup: boolean;
  worker_poll_seconds: number;
  download_pdfs: boolean;
  dense_index_policy: "if_present" | "always" | "never" | string;
  manual_trigger_allowed: boolean;
  running: boolean;
  manual_request_pending: boolean;
  manual_requested_at: string | null;
  manual_requested_by: string | null;
  last_success_at: string | null;
  last_failure_at: string | null;
  next_scheduled_at: string | null;
  last_run: IngestionRun | null;
  recent_runs: IngestionRun[];
};

export type ReviewQueueItem = {
  item_type:
    | "paper"
    | "rag_answer"
    | "thesis_recommendation"
    | "paper_artifact"
    | "author"
    | "author_alias"
    | "topic"
    | "paper_topic"
    | "author_topic";
  item_id: string;
  title: string;
  label: string;
  status: ReviewStatus | string;
  grounding_status: "grounded" | "partial" | "unsupported" | null;
  warnings: string[];
  approval_blockers?: string[];
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

export type ReviewEventsResponse = {
  total: number;
  limit: number;
  offset: number;
  items: ReviewEvent[];
};

export type EvaluationSectionStatus = {
  status: "not_run" | "available" | "invalid" | "historical";
  result_file_exists: boolean;
  path: string;
  last_run_timestamp: string | null;
  freshness_status?: "current" | "historical" | "missing" | "invalid";
  [key: string]: unknown;
};

export type EvaluationV2QaSummary = {
  case_count: number;
  counts?: Record<string, number>;
  metrics: {
    answerability_precision?: number | null;
    answerability_recall?: number | null;
    false_positive_rate?: number | null;
    abstention_rate?: number | null;
    abstention_accuracy?: number | null;
    exact_gold_locator_citation_precision?: number | null;
    citation_completeness?: number | null;
    returned_citation_utilization?: number | null;
    answer_point_coverage?: number | null;
  };
};

export type EvaluationV2FinderSummary = {
  profile_count: number;
  counts?: Record<string, number>;
  metrics: {
    evidence_only_hit_at_3?: number | null;
    full_finder_hit_at_3?: number | null;
    paired_hit_at_3_delta?: number | null;
    evidence_only_mrr?: number | null;
    full_finder_mrr?: number | null;
    paired_mrr_delta?: number | null;
    candidate_specific_template_conformance_rate?: number | null;
    source_fact_suggestion_separation_rate?: number | null;
    unknown_implementation_time_retention_rate?: number | null;
    full_profile_constraint_contract_fidelity_rate?: number | null;
  };
};

export type EvaluationV2TopicSummary = {
  case_count: number;
  vocabulary_size?: number;
  label_scope?: "positive_only_not_exhaustive_closed_world" | string;
  known_positive_micro?: {
    matched?: number;
    missed?: number;
    recall?: number | null;
  };
  known_positive_case_coverage_rate?: number | null;
  unadjudicated_predictions?: {
    count?: number;
    total_predictions?: number;
    share?: number | null;
    false_positive_interpretation_permitted?: boolean;
  };
};

export type EvaluationV2OcrSummary = {
  status?: string;
  metrics?: {
    normalized_exact_match?: boolean;
    character_error_rate?: number | null;
    word_error_rate?: number | null;
    repeat_run_text_identical?: boolean;
    repeat_run_text_artifact_identical?: boolean;
    repeat_run_configuration_identical?: boolean;
    repeat_run_sanitized_pipeline_result_identical?: boolean;
    ocr_status?: string;
  };
  claim_boundary?: string;
};

export type EvaluationV2Package = {
  status: string;
  package_status?: string;
  evaluation_id?: string | null;
  evidence_tier: string;
  reviewer_type?: string | null;
  human_validation: boolean;
  entailment_claimed?: boolean;
  technical_scope_only?: boolean;
  public_projection_exercised?: boolean;
  qa_test?: EvaluationV2QaSummary | null;
  finder_test?: EvaluationV2FinderSummary | null;
  topics_test?: EvaluationV2TopicSummary | null;
  ocr?: EvaluationV2OcrSummary | null;
  claim_boundary?: string | null;
  manifest_path?: string;
  result_files?: Record<string, { path: string; exists: boolean; last_modified: string | null }>;
};

export type EvaluationV2Freshness = {
  status: "current" | "stale" | "not_run" | "invalid" | string;
  path?: string;
  checks?: Record<string, string>;
  identity_mismatches?: Record<string, string[]>;
  errors?: string[];
  freshness_contract?: string;
  head_commit_compared?: boolean;
  docs_only_commits_affect_freshness?: boolean;
};

export type EvaluationDashboard = {
  evaluation_label?: string;
  reviewer_type?: string;
  human_validation?: boolean;
  evaluation_status?: "current" | "historical" | "not_run" | "invalid" | string;
  freshness?: {
    status: "current" | "historical" | string;
    notice: string;
    current_commit?: string;
    current_corpus_snapshot_hash?: string;
    current_configuration_hash?: string;
    peer_review_remediation_v2?: EvaluationV2Freshness;
    artifacts?: Record<string, {
      status: string;
      checks?: Record<string, string>;
      recorded_commit?: string | null;
      recorded_corpus_snapshot_hash?: string | null;
      recorded_configuration_hash?: string | null;
      path?: string;
    }>;
  };
  peer_review_remediation_v2?: EvaluationV2Package;
  retrieval: EvaluationSectionStatus & {
    question_count: number;
    recall_at_3: number | null;
    recall_at_5: number | null;
    recall_at_10?: number | null;
    mrr: number | null;
    ndcg_at_10?: number | null;
    development_count?: number;
    test_count?: number;
    reported_mode?: string;
    tuned_hybrid_recall_at_10?: number;
    tuned_hybrid_mrr?: number;
    unanswerable_false_positive_rate?: number;
    reviewer_type?: string;
    dataset_label?: string;
    statistical_conclusion?: string;
  };
  qa: EvaluationSectionStatus & {
    question_count: number;
    answer_count: number;
    cited_gold_paper_count: number;
    citation_count: number;
    claim_count?: number;
    supported_claim_rate?: number;
    citation_correctness?: number;
    citation_completeness?: number;
    answer_point_coverage?: number;
    unsupported_claim_rate?: number;
    unanswerable_abstention_rate?: number;
    reviewer_type?: string;
    grounding_counts: Record<string, number>;
  };
  extension: EvaluationSectionStatus & {
    case_count: number;
    recommendation_count: number;
    citation_coverage: number | null;
    grounding_counts: Record<string, number>;
    warnings_count: number;
    evidence_only_relevance?: number;
    full_finder_relevance?: number;
    relevance_difference?: number;
    relevance_difference_ci?: [number, number];
    reviewer_type?: string;
    proxy_notice?: string;
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
    ai_reviewed_count?: number;
    needs_reprocess_count?: number;
    review_event_count?: number;
    citation_evidence_locator_count?: number;
    reviewer_type?: string;
    review_notice?: string;
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
  demo_preview?: boolean;
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
  demo_preview?: boolean;
  corpus_access_mode?: "approved_public_projection" | "unreviewed_local_demo_preview";
};

export type ServiceStatus = {
  service: string;
  status: string;
  security_mode: "local_demo" | "production" | string;
  admin_authentication: "insecure_local_demo_bypass" | "bearer_token_required" | string;
  frontend: string;
  api_docs: string;
  health: string;
  readiness: string;
  corpus_access_mode?: "approved_public_projection" | "unreviewed_local_demo_preview";
};

export type PaginatedTopics = {
  total: number;
  limit: number;
  offset: number;
  items: TopicSummary[];
  demo_preview?: boolean;
  corpus_access_mode?: "approved_public_projection" | "unreviewed_local_demo_preview";
};

export type PaginatedAuthors = {
  total: number;
  limit: number;
  offset: number;
  items: AuthorSummary[];
  demo_preview?: boolean;
  corpus_access_mode?: "approved_public_projection" | "unreviewed_local_demo_preview";
};

export type RelatedPaper = PaperSummary & {
  score: number;
  reason: string;
  shared_topics: string[];
  shared_authors: string[];
  source_basis: string[];
};
