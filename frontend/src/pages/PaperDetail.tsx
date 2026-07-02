import { useEffect, useState } from "react";

import { fetchExtraction, fetchPaperArtifacts, fetchPaperChunks, generatePaperArtifacts } from "../api/client";
import { StatusBadge } from "../components/StatusBadge";
import type {
  ArtifactCitation,
  ArtifactSection,
  ExtractionDiagnostics,
  Paper,
  PaperArtifact,
  PaperChunk,
  PaperIntelligenceBundle,
  PodcastScriptArtifact,
} from "../types/paper";

type PaperDetailProps = {
  paper: Paper;
  onBack: () => void;
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

export function PaperDetail({ paper, onBack }: PaperDetailProps) {
  const [extraction, setExtraction] = useState<ExtractionDiagnostics | null>(null);
  const [chunks, setChunks] = useState<PaperChunk[]>([]);
  const [artifacts, setArtifacts] = useState<PaperArtifact[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [artifactError, setArtifactError] = useState<string | null>(null);
  const [artifactLoading, setArtifactLoading] = useState(false);
  const [activeArtifactTab, setActiveArtifactTab] = useState<ArtifactTab>("public_summary");

  useEffect(() => {
    setError(null);
    setArtifactError(null);
    Promise.all([fetchExtraction(paper.paper_id), fetchPaperChunks(paper.paper_id), fetchPaperArtifacts(paper.paper_id)])
      .then(([extractionData, chunkRows, artifactRows]) => {
        setExtraction(extractionData);
        setChunks(chunkRows);
        setArtifacts(artifactRows);
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

  const bundleArtifact = artifacts.find((artifact) => artifact.artifact_type === "paper_intelligence_bundle");
  const podcastArtifact = artifacts.find((artifact) => artifact.artifact_type === "podcast_script");
  const bundle = isPaperBundle(bundleArtifact?.generated_json) ? bundleArtifact.generated_json : null;
  const podcast = isPodcastScript(podcastArtifact?.generated_json) ? podcastArtifact.generated_json : null;
  const latestArtifact = bundleArtifact ?? podcastArtifact;

  function generateArtifacts() {
    setArtifactLoading(true);
    setArtifactError(null);
    generatePaperArtifacts(paper.paper_id)
      .then((response) => setArtifacts(response.artifacts))
      .catch((err: unknown) => setArtifactError(err instanceof Error ? err.message : "Unable to generate paper intelligence."))
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
        <h2>Paper Intelligence</h2>
        <button className="action-button" onClick={generateArtifacts} disabled={artifactLoading || chunks.length === 0}>
          {artifactLoading ? "Generating..." : artifacts.length ? "Refresh Artifacts" : "Generate Artifacts"}
        </button>
      </div>
      <p className="notice notice--warning">
        These outputs are AI-assisted and source-grounded where possible. They are not reviewed yet.
      </p>
      {artifactError ? <p className="notice notice--error">{artifactError}</p> : null}
      {latestArtifact ? (
        <div className="paper-card__badges paper-card__badges--left">
          <StatusBadge label={latestArtifact.review_status} tone="warn" />
          <StatusBadge label={latestArtifact.grounding_status} tone={latestArtifact.grounding_status === "grounded" ? "good" : "warn"} />
        </div>
      ) : null}
      {bundle || podcast ? (
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
        <p className="empty-state">No paper intelligence artifacts have been generated for this paper yet.</p>
      )}

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

function renderArtifactTab(
  activeTab: ArtifactTab,
  bundle: PaperIntelligenceBundle | null,
  podcast: PodcastScriptArtifact | null,
) {
  if (!bundle && activeTab !== "podcast_script") {
    return <p className="empty-state">Generate the paper intelligence bundle to view this section.</p>;
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
  return podcast ? <PodcastArtifact podcast={podcast} /> : <p className="empty-state">Generate the podcast script artifact to view this section.</p>;
}

function SectionArtifact({ title, section }: { title: string; section: ArtifactSection | undefined }) {
  if (!section) {
    return <p className="empty-state">This artifact section is not available yet.</p>;
  }
  const supportStatus = section.support_status ?? section.basis;
  return (
    <article className="artifact-card">
      <div className="paper-card__meta">
        {supportStatus ? <span className="grounding grounding--partial">{String(supportStatus).replaceAll("_", " ")}</span> : null}
      </div>
      <h3>{title}</h3>
      <p>{section.text}</p>
      <CitationList citations={section.citations ?? []} />
    </article>
  );
}

function ExtensionsArtifact({ extensions }: { extensions: PaperIntelligenceBundle["possible_extensions"] }) {
  if (!extensions.length) {
    return <p className="empty-state">No extension suggestions are available yet.</p>;
  }
  return (
    <div className="paper-list">
      {extensions.map((extension) => (
        <article className="artifact-card" key={extension.title}>
          <div className="paper-card__meta">
            <span className="grounding grounding--partial">{extension.support_status.replaceAll("_", " ")}</span>
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
    return <p className="empty-state">Required skills are not available yet.</p>;
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
        <span>{podcast.review_status}</span>
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
    return <p className="empty-state">No citations available for this section.</p>;
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
