import { useEffect, useState } from "react";

import { fetchExtraction, fetchPaperArtifacts, fetchPaperChunks, fetchRelatedPapers, generatePaperArtifacts } from "../api/client";
import { StatusBadge } from "../components/StatusBadge";
import { EmptyState, GenerateButton, InlineProgress, ListSkeleton, MetricSkeletonGrid } from "../components/UiPrimitives";
import type { ToastTone } from "../components/UiPrimitives";
import type {
  ArtifactCitation,
  ArtifactSection,
  ExtractionDiagnostics,
  Paper,
  PaperArtifact,
  PaperChunk,
  PaperIntelligenceBundle,
  PodcastScriptArtifact,
  RelatedPaper,
} from "../types/paper";

type PaperDetailProps = {
  paper: Paper;
  onBack: () => void;
  onSelectPaper?: (paperId: string) => void;
  onAskPaper?: (paperId: string) => void;
  onNotify?: (message: string, tone?: ToastTone) => void;
};

type ArtifactTab =
  | "public_summary"
  | "technical_summary"
  | "contribution"
  | "methods"
  | "limitations"
  | "future_work"
  | "possible_extensions"
  | "required_skills"
  | "evaluation_plan"
  | "podcast_script";

const ARTIFACT_TABS: { id: ArtifactTab; label: string }[] = [
  { id: "public_summary", label: "Public Summary" },
  { id: "technical_summary", label: "Technical Summary" },
  { id: "contribution", label: "Contribution" },
  { id: "methods", label: "Methods" },
  { id: "limitations", label: "Limitations" },
  { id: "future_work", label: "Future Work" },
  { id: "possible_extensions", label: "Extensions" },
  { id: "required_skills", label: "Required Skills" },
  { id: "evaluation_plan", label: "Evaluation Plan" },
  { id: "podcast_script", label: "Podcast Script" },
];

export function PaperDetail({ paper, onBack, onSelectPaper, onAskPaper, onNotify }: PaperDetailProps) {
  const [extraction, setExtraction] = useState<ExtractionDiagnostics | null>(null);
  const [chunks, setChunks] = useState<PaperChunk[]>([]);
  const [artifacts, setArtifacts] = useState<PaperArtifact[]>([]);
  const [relatedPapers, setRelatedPapers] = useState<RelatedPaper[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [artifactError, setArtifactError] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(true);
  const [artifactLoading, setArtifactLoading] = useState(false);
  const [activeArtifactTab, setActiveArtifactTab] = useState<ArtifactTab>("public_summary");

  useEffect(() => {
    setError(null);
    setArtifactError(null);
    setDetailLoading(true);
    setExtraction(null);
    setChunks([]);
    setArtifacts([]);
    setRelatedPapers([]);
    Promise.all([
      fetchExtraction(paper.paper_id),
      fetchPaperChunks(paper.paper_id),
      fetchPaperArtifacts(paper.paper_id),
      fetchRelatedPapers(paper.paper_id),
    ])
      .then(([extractionData, chunkRows, artifactRows, relatedRows]) => {
        setExtraction(extractionData);
        setChunks(chunkRows);
        setArtifacts(artifactRows);
        setRelatedPapers(relatedRows);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Unable to load paper detail."))
      .finally(() => setDetailLoading(false));
  }, [paper.paper_id]);

  const warning =
    paper.pdf_text_status === "missing_pdf"
      ? "No direct PDF URL was discovered for this publication."
      : extraction?.possible_scanned_pdf
        ? "This PDF may be scanned or image-heavy; extracted text is limited."
        : extraction?.extraction_error
          ? "Text extraction failed for this PDF."
          : null;

  const bundleArtifact = artifacts.find((artifact) => artifact.artifact_type === "paper_intelligence_bundle");
  const podcastArtifact = artifacts.find((artifact) => artifact.artifact_type === "podcast_script");
  const bundle = isPaperBundle(bundleArtifact?.generated_json) ? bundleArtifact.generated_json : null;
  const podcast = isPodcastScript(podcastArtifact?.generated_json) ? podcastArtifact.generated_json : null;
  const latestArtifact = bundleArtifact ?? podcastArtifact;

  function generateArtifacts() {
    setArtifactLoading(true);
    setArtifactError(null);
    generatePaperArtifacts(paper.paper_id)
      .then((response) => {
        setArtifacts(response.artifacts);
        onNotify?.(`Generated ${response.artifacts.length} paper intelligence artifacts.`, response.grounding_status === "unsupported" ? "warning" : "success");
      })
      .catch((err: unknown) => {
        const message = err instanceof Error ? err.message : "Unable to generate paper intelligence.";
        setArtifactError(message);
        onNotify?.(message, "error");
      })
      .finally(() => setArtifactLoading(false));
  }

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
          {onAskPaper ? (
            <button className="link-button" onClick={() => onAskPaper(paper.paper_id)}>
              Ask about this paper
            </button>
          ) : null}
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

      {detailLoading ? (
        <MetricSkeletonGrid count={4} compact />
      ) : (
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
      )}

      <div className="section-heading">
        <h2>Paper Intelligence</h2>
        <GenerateButton
          busy={artifactLoading}
          onClick={generateArtifacts}
          disabled={detailLoading || chunks.length === 0}
          busyLabel={artifacts.length ? "Refreshing..." : "Generating..."}
        >
          {artifacts.length ? "Refresh Artifacts" : "Generate Artifacts"}
        </GenerateButton>
      </div>
      <p className="notice notice--warning">
        These outputs are AI-assisted and source-grounded where possible. They are not reviewed yet.
      </p>
      {artifactLoading && (bundle || podcast) ? <InlineProgress label="Refreshing paper intelligence while keeping the current artifacts visible..." /> : null}
      {artifactError ? <p className="notice notice--error">{artifactError}</p> : null}
      {latestArtifact ? (
        <div className="paper-card__badges paper-card__badges--left">
          <StatusBadge label={latestArtifact.review_status} tone="warn" />
          <StatusBadge label={latestArtifact.grounding_status} tone={latestArtifact.grounding_status === "grounded" ? "good" : "warn"} />
        </div>
      ) : null}
      {detailLoading || (artifactLoading && !bundle && !podcast) ? (
        <ListSkeleton count={1} lines={5} />
      ) : bundle || podcast ? (
        <div className="artifact-panel">
          <div className="artifact-tabs" aria-label="Paper intelligence sections">
            {ARTIFACT_TABS.map((tab) => (
              <button
                key={tab.id}
                className={activeArtifactTab === tab.id ? "active" : ""}
                onClick={() => setActiveArtifactTab(tab.id)}
              >
                {tab.label}
              </button>
            ))}
          </div>
          {renderArtifactTab(activeArtifactTab, bundle, podcast)}
        </div>
      ) : (
        <EmptyState
          title="No paper intelligence artifacts yet"
          body="Generate artifacts after chunks are available to show summaries, limitations, extensions, skills, evaluation plans, and podcast script text."
        />
      )}

      <div className="section-heading">
        <h2>Related Papers</h2>
      </div>
      <div className="paper-list">
        {detailLoading ? <ListSkeleton count={2} lines={2} /> : null}
        {!detailLoading && relatedPapers.map((related) => (
          <article className="paper-row" key={related.paper_id}>
            <div>
              <div className="paper-card__meta">
                <span>{related.year ?? "Year needs review"}</span>
                <span>Score {related.score.toFixed(2)}</span>
              </div>
              <h3>{related.title}</h3>
              <p>{related.reason || "Related by deterministic metadata and topic scoring."}</p>
              <div className="chip-row chip-row--compact">
                {related.shared_topics.map((topic) => (
                  <span key={topic}>{topic}</span>
                ))}
                {related.shared_authors.map((author) => (
                  <span key={author}>{author}</span>
                ))}
              </div>
              <p className="paper-card__status">Basis: {related.source_basis.join(", ") || "metadata"}</p>
            </div>
            {onSelectPaper ? (
              <button className="action-button" onClick={() => onSelectPaper(related.paper_id)}>
                Open Paper
              </button>
            ) : null}
          </article>
        ))}
        {!detailLoading && !relatedPapers.length ? (
          <EmptyState
            title="No related papers found yet"
            body="Run topic rebuild: PYTHONPATH=backend .venv/bin/python -m app.intelligence.topic_explorer rebuild"
          />
        ) : null}
      </div>

      <div className="section-heading">
        <h2>Chunk Preview</h2>
      </div>
      <div className="paper-list">
        {detailLoading ? <ListSkeleton count={3} lines={3} /> : null}
        {!detailLoading && chunks.map((chunk) => (
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
        {!detailLoading && chunks.length === 0 ? (
          <EmptyState
            title="No chunks have been generated"
            body="Extract and chunk this PDF before search, Ask TTLAB, and paper intelligence can use full-paper text."
          />
        ) : null}
      </div>
    </section>
  );
}

function renderArtifactTab(
  activeTab: ArtifactTab,
  bundle: PaperIntelligenceBundle | null,
  podcast: PodcastScriptArtifact | null,
) {
  if (!bundle && activeTab !== "podcast_script") {
    return <EmptyState title="Generate the paper intelligence bundle" body="This section appears after source-grounded artifacts are generated for the paper." />;
  }
  if (activeTab === "public_summary") {
    return <SectionArtifact title="Public Summary" section={bundle?.public_summary} />;
  }
  if (activeTab === "technical_summary") {
    return <SectionArtifact title="Technical Summary" section={bundle?.technical_summary} />;
  }
  if (activeTab === "contribution") {
    return <SectionArtifact title="Contribution" section={bundle?.contribution} />;
  }
  if (activeTab === "methods") {
    return <SectionArtifact title="Methods / Approach" section={bundle?.methods} />;
  }
  if (activeTab === "limitations") {
    return <SectionArtifact title="Limitations" section={bundle?.limitations} />;
  }
  if (activeTab === "future_work") {
    return <SectionArtifact title="Future Work" section={bundle?.future_work} />;
  }
  if (activeTab === "possible_extensions") {
    return <ExtensionsArtifact extensions={bundle?.possible_extensions ?? []} />;
  }
  if (activeTab === "required_skills") {
    return <SkillsArtifact section={bundle?.required_skills} />;
  }
  if (activeTab === "evaluation_plan") {
    return <SectionArtifact title="Evaluation Plan" section={bundle?.evaluation_plan} />;
  }
  return podcast ? <PodcastArtifact podcast={podcast} /> : <EmptyState title="Generate the podcast script" body="Podcast scripts are text only and appear after paper artifacts are generated." />;
}

function SectionArtifact({ title, section }: { title: string; section: ArtifactSection | undefined }) {
  if (!section) {
    return <EmptyState title="Artifact section unavailable" body="Refresh or generate paper intelligence artifacts to populate this section." />;
  }
  const supportStatus = section.support_status ?? section.basis;
  return (
    <article className="artifact-card">
      <div className="paper-card__meta">
        {supportStatus ? <StatusBadge label={String(supportStatus)} /> : null}
      </div>
      <h3>{title}</h3>
      <p>{section.text}</p>
      <CitationList citations={section.citations ?? []} />
    </article>
  );
}

function ExtensionsArtifact({ extensions }: { extensions: PaperIntelligenceBundle["possible_extensions"] }) {
  if (!extensions.length) {
    return <EmptyState title="No extension suggestions available" body="Generate or refresh paper intelligence artifacts to create source-based extension ideas." />;
  }
  return (
    <div className="paper-list">
      {extensions.map((extension) => (
        <article className="artifact-card" key={extension.title}>
          <div className="paper-card__meta">
            <StatusBadge label={extension.support_status} />
          </div>
          <h3>{extension.title}</h3>
          <p>{extension.summary}</p>
          <CitationList citations={extension.citations} />
        </article>
      ))}
    </div>
  );
}

function SkillsArtifact({ section }: { section: ArtifactSection | undefined }) {
  if (!section) {
    return <EmptyState title="Required skills unavailable" body="Generate paper intelligence artifacts to infer skills from methods and implementation details." />;
  }
  return (
    <article className="artifact-card">
      <h3>Required Skills</h3>
      <div className="chip-row chip-row--compact">
        {(section.skills ?? []).map((skill) => (
          <span key={skill}>{skill}</span>
        ))}
      </div>
      {section.basis ? <p>{section.basis}</p> : null}
      <CitationList citations={section.citations ?? []} />
    </article>
  );
}

function PodcastArtifact({ podcast }: { podcast: PodcastScriptArtifact }) {
  return (
    <article className="artifact-card">
      <div className="paper-card__meta">
        <span>{podcast.duration_target}</span>
        <StatusBadge label={podcast.review_status} />
      </div>
      <h3>{podcast.episode_title}</h3>
      <p>{podcast.short_description}</p>
      <div className="dialogue-list">
        {podcast.script.map((line, index) => (
          <p key={`${line.speaker}-${index}`}>
            <strong>{line.speaker}:</strong> {line.text}
          </p>
        ))}
      </div>
      <CitationList citations={podcast.citations} />
      {podcast.warnings.length ? <p className="notice notice--warning">{podcast.warnings.join(" ")}</p> : null}
    </article>
  );
}

function CitationList({ citations }: { citations: ArtifactCitation[] }) {
  if (!citations.length) {
    return <EmptyState title="No citations available" body="Treat this section as weakly grounded until source chunks are available." />;
  }
  return (
    <details className="retrieved-details" open>
      <summary>Citations</summary>
      <div className="paper-list">
        {citations.map((citation) => (
          <article className="citation-card" key={citation.chunk_id}>
            <div className="paper-card__meta">
              <span>{citation.section ?? "Unknown section"}</span>
              <span>Pages {citation.page_start ?? "?"}-{citation.page_end ?? "?"}</span>
            </div>
            <h3>{citation.title}</h3>
            <p>{citation.snippet}</p>
          </article>
        ))}
      </div>
    </details>
  );
}

function isPaperBundle(value: PaperArtifact["generated_json"] | undefined): value is PaperIntelligenceBundle {
  if (!value || typeof value !== "object") {
    return false;
  }
  const candidate = value as Partial<PaperIntelligenceBundle>;
  return Boolean(candidate.public_summary && candidate.technical_summary && Array.isArray(candidate.possible_extensions));
}

function isPodcastScript(value: PaperArtifact["generated_json"] | undefined): value is PodcastScriptArtifact {
  if (!value || typeof value !== "object") {
    return false;
  }
  const candidate = value as Partial<PodcastScriptArtifact>;
  return Boolean(candidate.episode_title && Array.isArray(candidate.script));
}
