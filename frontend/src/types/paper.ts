export type Paper = {
  paper_id: string;
  title: string;
  authors: string[];
  year: number | null;
  publication_date_raw: string | null;
  venue: string | null;
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
  review_status: string;
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
