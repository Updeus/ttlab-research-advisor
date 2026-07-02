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
