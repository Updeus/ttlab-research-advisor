import { useEffect, useState } from "react";

import { fetchExtensionDiagnostics, recommendExtensions } from "../api/client";
import type {
  ExtensionDiagnostics,
  ExtensionFinderRequest,
  ExtensionFinderResponse,
  ExtensionRecommendation,
  Paper,
  SearchMode,
} from "../types/paper";

type ThesisExtensionFinderProps = {
  papers: Paper[];
  onSelectPaper: (paperId: string) => void;
};

const DEFAULT_REQUEST: ExtensionFinderRequest = {
  interests: "RAG, web apps, education",
  skills: ["Python", "React", "FastAPI"],
  available_time: "semester",
  project_type: "software prototype",
  data_constraints: "prefer public or synthetic data",
  preferred_difficulty: "medium",
  preferred_topics: ["AI", "research discovery"],
  avoid_topics: [],
  top_k: 5,
  retrieval_mode: "hybrid",
  provider: "auto",
};

export function ThesisExtensionFinder({ papers, onSelectPaper }: ThesisExtensionFinderProps) {
  const [request, setRequest] = useState<ExtensionFinderRequest>(DEFAULT_REQUEST);
  const [skillsText, setSkillsText] = useState(DEFAULT_REQUEST.skills.join(", "));
  const [preferredTopicsText, setPreferredTopicsText] = useState(DEFAULT_REQUEST.preferred_topics.join(", "));
  const [avoidTopicsText, setAvoidTopicsText] = useState("");
  const [response, setResponse] = useState<ExtensionFinderResponse | null>(null);
  const [diagnostics, setDiagnostics] = useState<ExtensionDiagnostics | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchExtensionDiagnostics()
      .then(setDiagnostics)
      .catch(() => setDiagnostics(null));
  }, []);

  function updateRequest(update: Partial<ExtensionFinderRequest>) {
    setRequest((current) => ({ ...current, ...update }));
  }

  function submit() {
    const payload: ExtensionFinderRequest = {
      ...request,
      skills: splitList(skillsText),
      preferred_topics: splitList(preferredTopicsText),
      avoid_topics: splitList(avoidTopicsText),
    };
    if (!payload.interests.trim()) {
      setError("Enter at least one student interest.");
      return;
    }
    setLoading(true);
    setError(null);
    recommendExtensions(payload)
      .then((result) => {
        setResponse(result);
        return fetchExtensionDiagnostics().then(setDiagnostics).catch(() => undefined);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Recommendation failed."))
      .finally(() => setLoading(false));
  }

  return (
    <section className="page-section">
      <div className="section-heading">
        <h2>Thesis Extension Finder</h2>
      </div>

      <p className="notice notice--warning">
        These are AI-assisted thesis extension suggestions. Paper facts are cited; extension ideas are suggestions and should be reviewed with a supervisor.
      </p>

      <div className="finder-panel">
        <label>
          <span>Interests</span>
          <textarea
            value={request.interests}
            onChange={(event) => updateRequest({ interests: event.target.value })}
            rows={4}
          />
        </label>
        <div className="finder-grid">
          <label>
            <span>Skills</span>
            <input value={skillsText} onChange={(event) => setSkillsText(event.target.value)} />
          </label>
          <label>
            <span>Available time</span>
            <select value={request.available_time} onChange={(event) => updateRequest({ available_time: event.target.value as ExtensionFinderRequest["available_time"] })}>
              <option value="2 weeks">2 weeks</option>
              <option value="1 month">1 month</option>
              <option value="semester">semester</option>
            </select>
          </label>
          <label>
            <span>Project type</span>
            <select value={request.project_type} onChange={(event) => updateRequest({ project_type: event.target.value as ExtensionFinderRequest["project_type"] })}>
              <option value="software prototype">software prototype</option>
              <option value="data analysis">data analysis</option>
              <option value="ML experiment">ML experiment</option>
              <option value="literature/systematic review support">literature/systematic review support</option>
              <option value="dashboard/visualization">dashboard/visualization</option>
              <option value="other">other</option>
            </select>
          </label>
          <label>
            <span>Data constraints</span>
            <select value={request.data_constraints} onChange={(event) => updateRequest({ data_constraints: event.target.value })}>
              <option value="public data preferred">public data preferred</option>
              <option value="synthetic data acceptable">synthetic data acceptable</option>
              <option value="needs supervisor data">needs supervisor data</option>
              <option value="no external data">no external data</option>
              <option value="prefer public or synthetic data">prefer public or synthetic data</option>
            </select>
          </label>
          <label>
            <span>Preferred difficulty</span>
            <select value={request.preferred_difficulty} onChange={(event) => updateRequest({ preferred_difficulty: event.target.value as ExtensionFinderRequest["preferred_difficulty"] })}>
              <option value="easy">easy</option>
              <option value="medium">medium</option>
              <option value="hard">hard</option>
            </select>
          </label>
          <label>
            <span>Recommendations</span>
            <select value={request.top_k} onChange={(event) => updateRequest({ top_k: Number(event.target.value) })}>
              <option value={3}>3</option>
              <option value={5}>5</option>
              <option value={8}>8</option>
            </select>
          </label>
          <label>
            <span>Preferred topics</span>
            <input value={preferredTopicsText} onChange={(event) => setPreferredTopicsText(event.target.value)} />
          </label>
          <label>
            <span>Avoid topics</span>
            <input value={avoidTopicsText} onChange={(event) => setAvoidTopicsText(event.target.value)} />
          </label>
          <label>
            <span>Retrieval mode</span>
            <select value={request.retrieval_mode} onChange={(event) => updateRequest({ retrieval_mode: event.target.value as SearchMode })}>
              <option value="keyword">keyword</option>
              <option value="semantic">semantic</option>
              <option value="hybrid">hybrid</option>
            </select>
          </label>
        </div>
        <button onClick={submit} disabled={loading}>
          {loading ? "Finding..." : "Find Thesis Extensions"}
        </button>
      </div>

      {diagnostics ? (
        <div className="search-diagnostics">
          <span>{diagnostics.searchable_chunks} searchable chunks</span>
          <span>{diagnostics.searchable_papers} papers with chunks</span>
          <span>{diagnostics.total_recommendation_runs} saved runs</span>
          <span>{diagnostics.default_provider.replaceAll("_", " ")}</span>
        </div>
      ) : null}

      {loading ? <p className="notice">Ranking candidate papers and checking citations...</p> : null}
      {error ? <p className="notice notice--error">{error}</p> : null}

      {response ? (
        <div className="answer-layout">
          <article className="answer-card">
            <div className="paper-card__meta">
              <span className={`grounding grounding--${response.grounding_status}`}>{response.grounding_status}</span>
              <span>{response.provider.replaceAll("_", " ")}</span>
              <span>{response.retrieval_mode}</span>
            </div>
            <h3>Recommendation Run</h3>
            <p>
              Generated {response.recommendations.length} structured recommendations from indexed TTLAB source chunks.
            </p>
          </article>

          {response.warnings.length ? <p className="notice notice--warning">{response.warnings.join(" ")}</p> : null}

          <div className="paper-list">
            {response.recommendations.map((recommendation) => (
              <RecommendationCard
                key={`${response.recommendation_id}-${recommendation.paper_id}`}
                recommendation={recommendation}
                paper={papers.find((item) => item.paper_id === recommendation.paper_id)}
                onSelectPaper={onSelectPaper}
              />
            ))}
            {response.recommendations.length === 0 ? (
              <p className="empty-state">No cited recommendation could be generated from the indexed chunks.</p>
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  );
}

function RecommendationCard({
  recommendation,
  paper,
  onSelectPaper,
}: {
  recommendation: ExtensionRecommendation;
  paper: Paper | undefined;
  onSelectPaper: (paperId: string) => void;
}) {
  return (
    <article className="recommendation-card">
      <div className="paper-card__meta">
        <span>Rank {recommendation.rank}</span>
        <span>Fit {recommendation.fit_score.toFixed(3)}</span>
        <span>{recommendation.year ?? "Year needs review"}</span>
        <span className={`grounding grounding--${recommendation.identified_gap.support_status === "explicit_in_paper" ? "grounded" : "partial"}`}>
          {recommendation.identified_gap.support_status.replaceAll("_", " ")}
        </span>
      </div>
      <h3>{recommendation.extension_title}</h3>
      <p className="paper-card__status">{recommendation.paper_title}</p>
      <p>{recommendation.authors.join(", ") || "Authors need review"}</p>

      <div className="paper-card__links">
        {paper ? <button className="link-button" onClick={() => onSelectPaper(recommendation.paper_id)}>Paper detail</button> : null}
        {recommendation.citations[0]?.source_url ? <a href={recommendation.citations[0].source_url} target="_blank" rel="noreferrer">Source</a> : null}
        {recommendation.citations[0]?.pdf_url ? <a href={recommendation.citations[0].pdf_url} target="_blank" rel="noreferrer">PDF</a> : null}
      </div>

      <div className="recommendation-grid">
        <section>
          <h4>Why It Fits</h4>
          <p>{recommendation.why_it_fits_student}</p>
        </section>
        <section>
          <h4>Paper Focus</h4>
          <p>{recommendation.paper_focus}</p>
        </section>
        <section>
          <h4>Identified Gap</h4>
          <p>{recommendation.identified_gap.text}</p>
        </section>
        <section>
          <h4>Suggested Extension</h4>
          <p>{recommendation.extension_summary}</p>
        </section>
        <section>
          <h4>MVP Scope</h4>
          <p>{recommendation.mvp_scope}</p>
        </section>
        <section>
          <h4>Evaluation Plan</h4>
          <p>{recommendation.evaluation_plan}</p>
        </section>
      </div>

      <div className="chip-row">
        <span>Difficulty: {recommendation.difficulty}</span>
        <span>Risk: {recommendation.risk_level}</span>
        <span>Time: {recommendation.implementation_time}</span>
        <span>Data: {recommendation.data_availability}</span>
      </div>

      <div className="recommendation-columns">
        <SmallList title="Required Skills" items={recommendation.required_skills} />
        <SmallList title="Skills Gap" items={recommendation.skills_gap.length ? recommendation.skills_gap : ["No direct skill gaps detected"]} />
        <SmallList title="Stretch Goals" items={recommendation.stretch_goals} />
        <SmallList title="Data Required" items={[recommendation.data_required]} />
      </div>

      <details className="retrieved-details" open>
        <summary>Source-supported facts</summary>
        <div className="paper-list">
          {recommendation.source_supported_facts.map((fact) => (
            <article className="chunk-preview" key={fact.chunk_id}>
              <div className="paper-card__meta">
                <span>Pages {fact.page_start ?? "?"}-{fact.page_end ?? "?"}</span>
                <span>{fact.chunk_id}</span>
              </div>
              <p>{fact.claim}</p>
            </article>
          ))}
        </div>
      </details>

      <details className="retrieved-details" open>
        <summary>Citations</summary>
        <div className="paper-list">
          {recommendation.citations.map((citation) => (
            <article className="citation-card" key={citation.chunk_id}>
              <div className="paper-card__meta">
                <span>{citation.section ?? "Unknown section"}</span>
                <span>Pages {citation.page_start ?? "?"}-{citation.page_end ?? "?"}</span>
                <span>Score {citation.score.toFixed(3)}</span>
              </div>
              <p>{citation.snippet}</p>
            </article>
          ))}
        </div>
      </details>

      {recommendation.related_papers.length ? (
        <details className="retrieved-details">
          <summary>Related papers</summary>
          <div className="paper-list">
            {recommendation.related_papers.map((related) => (
              <article className="chunk-preview" key={related.paper_id}>
                <h3>{related.title}</h3>
                <p>{related.reason}</p>
              </article>
            ))}
          </div>
        </details>
      ) : null}

      {recommendation.potential_researcher_fit.length ? (
        <details className="retrieved-details">
          <summary>Potential researcher fit</summary>
          <div className="paper-list">
            {recommendation.potential_researcher_fit.map((researcher) => (
              <article className="chunk-preview" key={researcher.name}>
                <h3>{researcher.name}</h3>
                <p>{researcher.reason}</p>
              </article>
            ))}
          </div>
        </details>
      ) : null}

      {recommendation.warnings.length ? <p className="notice notice--warning">{recommendation.warnings.join(" ")}</p> : null}
    </article>
  );
}

function SmallList({ title, items }: { title: string; items: string[] }) {
  return (
    <section>
      <h4>{title}</h4>
      <div className="chip-row chip-row--compact">
        {items.map((item) => (
          <span key={item}>{item}</span>
        ))}
      </div>
    </section>
  );
}

function splitList(value: string): string[] {
  return value
    .split(/[,\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}
