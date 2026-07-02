import { useEffect, useState } from "react";

import { fetchExtraction, fetchPaperChunks } from "../api/client";
import { StatusBadge } from "../components/StatusBadge";
import type { ExtractionDiagnostics, Paper, PaperChunk } from "../types/paper";

type PaperDetailProps = {
  paper: Paper;
  onBack: () => void;
};

export function PaperDetail({ paper, onBack }: PaperDetailProps) {
  const [extraction, setExtraction] = useState<ExtractionDiagnostics | null>(null);
  const [chunks, setChunks] = useState<PaperChunk[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([fetchExtraction(paper.paper_id), fetchPaperChunks(paper.paper_id)])
      .then(([extractionData, chunkRows]) => {
        setExtraction(extractionData);
        setChunks(chunkRows);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Unable to load paper detail."));
  }, [paper.paper_id]);

  const warning =
    paper.pdf_text_status === "missing_pdf"
      ? "No direct PDF URL was discovered for this publication."
      : extraction?.possible_scanned_pdf
        ? "This PDF may be scanned or image-heavy; extracted text is limited."
        : extraction?.extraction_error
          ? "Text extraction failed for this PDF."
          : null;

  return (
    <section className="page-section">
      <button className="back-button" onClick={onBack}>
        Back to papers
      </button>

      <article className="detail-panel">
        <div className="paper-card__meta">
          <span>{paper.year ?? paper.publication_date_raw ?? "Date needs review"}</span>
          {paper.venue ? <span>{paper.venue}</span> : <span>Venue needs review</span>}
        </div>
        <h2>{paper.title}</h2>
        <p>{paper.authors.join(", ") || "Authors need review"}</p>
        <div className="paper-card__badges paper-card__badges--left">
          <StatusBadge label={paper.pdf_text_status} tone={paper.pdf_text_status === "extracted" ? "good" : "warn"} />
          <StatusBadge label={paper.review_status} />
        </div>
        <div className="paper-card__links">
          {paper.source_url ? (
            <a href={paper.source_url} target="_blank" rel="noreferrer">
              Source
            </a>
          ) : null}
          {paper.pdf_url ? (
            <a href={paper.pdf_url} target="_blank" rel="noreferrer">
              PDF
            </a>
          ) : null}
        </div>
      </article>

      {error ? <p className="notice notice--error">{error}</p> : null}
      {warning ? <p className="notice notice--warning">{warning}</p> : null}

      <div className="detail-grid">
        <article className="metric">
          <span className="metric__label">Pages</span>
          <strong>{extraction?.page_count ?? paper.page_count ?? 0}</strong>
        </article>
        <article className="metric">
          <span className="metric__label">Words</span>
          <strong>{extraction?.total_word_count ?? paper.total_word_count ?? 0}</strong>
        </article>
        <article className="metric">
          <span className="metric__label">Pages with text</span>
          <strong>{extraction?.pages_with_text ?? paper.pages_with_text ?? 0}</strong>
        </article>
        <article className="metric">
          <span className="metric__label">Chunks</span>
          <strong>{chunks.length}</strong>
        </article>
      </div>

      <div className="section-heading">
        <h2>Chunk Preview</h2>
      </div>
      <div className="paper-list">
        {chunks.map((chunk) => (
          <article className="chunk-preview" key={chunk.chunk_id}>
            <div className="paper-card__meta">
              <span>Chunk {chunk.chunk_index + 1}</span>
              <span>
                Pages {chunk.page_start ?? "?"}-{chunk.page_end ?? "?"}
              </span>
              <span>{chunk.section ?? "Unknown"}</span>
            </div>
            <p>{chunk.snippet}</p>
          </article>
        ))}
        {chunks.length === 0 ? <p className="empty-state">No chunks have been generated for this paper yet.</p> : null}
      </div>
    </section>
  );
}
