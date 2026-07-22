import { useEffect, useRef, useState } from "react";

import { fetchExtensionDiagnostics, isAbortError, recommendExtensions, searchChunks } from "../api/client";
import { EmptyState, GenerateButton, InlineProgress, ListSkeleton } from "../components/UiPrimitives";
import type { ToastTone } from "../components/UiPrimitives";
import type {
  ExtensionDiagnostics,
  ExtensionFinderRequest,
  ExtensionFinderResponse,
  ExtensionRecommendation,
  Paper,
  SearchResponse,
  SearchMode,
} from "../types/paper";

type ThesisExtensionFinderProps = {
  papers: Paper[];
  onSelectPaper: (paperId: string) => void;
  onNotify?: (message: string, tone?: ToastTone) => void;
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
  retrieval_mode: "keyword",
  provider: "auto",
};

type FinderResult =
  | { mode: "advisor"; profile: ExtensionFinderRequest; payload: ExtensionFinderResponse }
  | { mode: "evidence_only"; profile: ExtensionFinderRequest; payload: SearchResponse };

export function ThesisExtensionFinder({ papers, onSelectPaper, onNotify }: ThesisExtensionFinderProps) {
  const [request, setRequest] = useState<ExtensionFinderRequest>(DEFAULT_REQUEST);
  const [skillsText, setSkillsText] = useState(DEFAULT_REQUEST.skills.join(", "));
  const [preferredTopicsText, setPreferredTopicsText] = useState(DEFAULT_REQUEST.preferred_topics.join(", "));
  const [avoidTopicsText, setAvoidTopicsText] = useState("");
  const [result, setResult] = useState<FinderResult | null>(null);
  const [failedRequest, setFailedRequest] = useState<{ mode: "advisor" | "evidence_only"; profile: ExtensionFinderRequest } | null>(null);
  const [diagnostics, setDiagnostics] = useState<ExtensionDiagnostics | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [diagnosticsError, setDiagnosticsError] = useState<string | null>(null);
  const [runMode, setRunMode] = useState<"advisor" | "evidence_only">("advisor");
  const requestSequence = useRef(0);
  const requestController = useRef<AbortController | null>(null);

  function loadDiagnostics() {
    setDiagnosticsError(null);
    fetchExtensionDiagnostics()
      .then(setDiagnostics)
      .catch((err: unknown) => {
        setDiagnostics(null);
        setDiagnosticsError(err instanceof Error ? err.message : "Finder diagnostics are unavailable.");
      });
  }

  useEffect(() => {
    loadDiagnostics();
  }, []);

  useEffect(() => () => requestController.current?.abort(), []);

  const publicCorpusEmpty = diagnostics !== null
    && (diagnostics.searchable_chunks === 0 || diagnostics.searchable_papers === 0);

  function updateRequest(update: Partial<ExtensionFinderRequest>) {
    setRequest((current) => ({ ...current, ...update }));
  }

  function submit(requestOverride?: { mode: "advisor" | "evidence_only"; profile: ExtensionFinderRequest }) {
    const payload: ExtensionFinderRequest = requestOverride?.profile ?? {
      ...request,
      skills: splitList(skillsText),
      preferred_topics: splitList(preferredTopicsText),
      avoid_topics: splitList(avoidTopicsText),
    };
    const submittedMode = requestOverride?.mode ?? runMode;
    if (!payload.interests.trim()) {
      setError("Enter at least one student interest.");
      return;
    }

    requestController.current?.abort();
    const controller = new AbortController();
    requestController.current = controller;
    const sequence = ++requestSequence.current;
    setLoading(true);
    setError(null);
    setFailedRequest(null);
    const operation = submittedMode === "evidence_only"
      ? searchChunks(profileQuery(payload), payload.retrieval_mode, Math.min(payload.top_k * 3, 20), controller.signal)
      : recommendExtensions(payload, controller.signal);
    operation
      .then((payloadResult) => {
        if (sequence !== requestSequence.current) return;
        if (submittedMode === "evidence_only") {
          const evidence = payloadResult as SearchResponse;
          setResult({ mode: "evidence_only", profile: payload, payload: evidence });
          onNotify?.(`Evidence-only retrieval returned ${evidence.result_count} source passages.`, evidence.result_count ? "success" : "warning");
        } else {
          const advisor = payloadResult as ExtensionFinderResponse;
          setResult({ mode: "advisor", profile: payload, payload: advisor });
          onNotify?.(`Generated ${advisor.recommendations.length} thesis recommendations.`, advisor.grounding_status === "unsupported" ? "warning" : "success");
        }
        loadDiagnostics();
      })
      .catch((err: unknown) => {
        if (sequence !== requestSequence.current || isAbortError(err)) return;
        const message = err instanceof Error ? err.message : "Recommendation failed.";
        setError(message);
        setFailedRequest({ mode: submittedMode, profile: payload });
        onNotify?.(message, "error");
      })
      .finally(() => {
        if (sequence === requestSequence.current) setLoading(false);
      });
  }

  return (
    <section className="page-section">
      <div className="section-heading">
        <h2>Thesis Extension Finder</h2>
      </div>

      <p className="notice notice--warning">
        These are AI-assisted thesis extension suggestions—not supervisor assignments. Paper facts are cited; fit rationales and extension ideas are system inferences or suggestions that require source checking and supervisor review.
      </p>
      <p className="notice">
        Privacy: interests, skills, timeline, constraints, and preferences stay in this page and are sent only for the current request. The public endpoint does not save the profile. Do not enter confidential or personal data.
      </p>
      <p className="notice">
        Finder evidence comes only from approved public papers with cleared rights, searchable access, and eligible extracted text. Metadata-only catalogue records are excluded.
      </p>

      <div className="finder-panel finder-panel--advisor" aria-busy={loading}>
        <div className="finder-sections">
          <section className="finder-section">
            <h3>Student Profile</h3>
            <label>
              <span>Interests</span>
              <textarea
                id="finder-interests"
                aria-invalid={Boolean(error && !request.interests.trim())}
                aria-describedby="finder-interests-help finder-error"
                value={request.interests}
                onChange={(event) => updateRequest({ interests: event.target.value })}
                rows={4}
              />
              <small id="finder-interests-help">Describe research areas or problems; at least one interest is required.</small>
            </label>
            <label>
              <span>Skills</span>
              <input value={skillsText} onChange={(event) => setSkillsText(event.target.value)} />
            </label>
          </section>

          <section className="finder-section">
            <h3>Project Constraints</h3>
            <div className="finder-grid finder-grid--compact">
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
            </div>
          </section>

          <section className="finder-section">
            <h3>Retrieval Focus</h3>
            <div className="finder-grid finder-grid--compact">
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
                  <option value="feature_hashing">feature-hashing baseline</option>
                  <option value="dense">dense semantic (learned model)</option>
                  <option value="hybrid">hybrid (experimental; not validated as better)</option>
                </select>
              </label>
            </div>
          </section>
        </div>
        <div className="finder-action-bar">
          <fieldset className="mode-choice">
            <legend>Finder output</legend>
            <label><input type="radio" name="finder-mode" checked={runMode === "advisor"} onChange={() => setRunMode("advisor")} /> Full advisor suggestions</label>
            <label><input type="radio" name="finder-mode" checked={runMode === "evidence_only"} onChange={() => setRunMode("evidence_only")} /> Evidence-only ranked papers/passages</label>
          </fieldset>
          <GenerateButton
            busy={loading}
            busyLabel="Finding..."
            onClick={() => submit()}
            disabled={!request.interests.trim() || publicCorpusEmpty}
            aria-describedby={publicCorpusEmpty ? "finder-public-corpus-empty" : undefined}
          >
            {runMode === "advisor" ? "Find Thesis Extensions" : "Retrieve Evidence Only"}
          </GenerateButton>
        </div>
      </div>

      {diagnostics ? (
        <div className="search-diagnostics">
          <span>{diagnostics.searchable_chunks} searchable chunks</span>
          <span>{diagnostics.searchable_papers} papers with chunks</span>
          <span>{diagnostics.total_recommendation_runs === null ? "Stored recommendation history protected" : `${diagnostics.total_recommendation_runs} stored reviewer/legacy runs`}</span>
          <span>{diagnostics.default_provider.replaceAll("_", " ")}</span>
        </div>
      ) : null}
      {publicCorpusEmpty ? (
        <div id="finder-public-corpus-empty" data-finder-public-corpus-state="empty">
          <EmptyState
            title="No papers are approved for public Finder recommendations yet"
            body="The public Finder remains disabled until editorial publication, document-rights, extraction, and searchable-access review produce an eligible public corpus. Reviewer-only technical prototype evidence is not substituted into this public route."
          />
        </div>
      ) : null}
      {diagnosticsError ? (
        <div className="notice notice--warning" role="status">
          <p>{diagnosticsError}</p>
          <button className="action-button" onClick={loadDiagnostics}>Retry diagnostics</button>
        </div>
      ) : null}

      {loading && result ? <InlineProgress label="Refreshing ranked recommendations and citation checks..." /> : null}
      {error ? (
        <div id="finder-error" className="notice notice--error" role="alert">
          <p>{error}</p>
          {failedRequest ? <button className="action-button" onClick={() => submit(failedRequest)}>Retry finder request</button> : null}
        </div>
      ) : null}
      {loading && !result ? <ListSkeleton count={Number(request.top_k) || 3} lines={5} /> : null}

      {result ? <ProfileEcho profile={result.profile} mode={result.mode} /> : null}

      {result?.mode === "evidence_only" ? <EvidenceOnlyResults response={result.payload} papers={papers} onSelectPaper={onSelectPaper} /> : null}

      {result?.mode === "advisor" ? (
        <div className="answer-layout">
          <article className="answer-card">
            <div className="paper-card__meta">
              <span className={`grounding grounding--${result.payload.grounding_status}`}>{result.payload.grounding_status}</span>
              <span>{result.payload.provider.replaceAll("_", " ")}</span>
              <span>{result.payload.retrieval_mode}</span>
              <span>{result.payload.model}</span>
              <span>Generated {new Date(result.payload.created_at).toLocaleString()}</span>
            </div>
            <p className="paper-card__status">
              Grounding status reports structural citations and weak lexical overlap; it does not establish entailment or factual correctness.
            </p>
            <h3>Recommendation Run</h3>
            <p>
              Generated {result.payload.recommendations.length} transient structured recommendations from indexed TTLAB source chunks. This public run was not saved or human-reviewed.
            </p>
          </article>

          {result.payload.warnings.length ? <p className="notice notice--warning">{result.payload.warnings.join(" ")}</p> : null}

          <div className="paper-list">
            {result.payload.recommendations.map((recommendation) => (
              <RecommendationCard
                key={`${result.payload.recommendation_id}-${recommendation.paper_id}`}
                recommendation={recommendation}
                paper={papers.find((item) => item.paper_id === recommendation.paper_id)}
                onSelectPaper={onSelectPaper}
              />
            ))}
            {result.payload.recommendations.length === 0 ? (
              <EmptyState
                title="No cited recommendation could be generated"
                body="Try broader interests. Recommendations use only approved public papers with searchable source evidence."
              />
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  );
}

function ProfileEcho({ profile, mode }: { profile: ExtensionFinderRequest; mode: "advisor" | "evidence_only" }) {
  return (
    <article className="profile-echo" aria-labelledby="submitted-profile-title">
      <div className="section-heading section-heading--compact">
        <h2 id="submitted-profile-title">Submitted profile (transient)</h2>
        <span>{mode === "advisor" ? "Full advisor suggestions" : "Evidence-only baseline"}</span>
      </div>
      <dl>
        <div><dt>Interests</dt><dd>{profile.interests}</dd></div>
        <div><dt>Skills</dt><dd>{profile.skills.join(", ") || "None stated"}</dd></div>
        <div><dt>Time / type</dt><dd>{profile.available_time} · {profile.project_type}</dd></div>
        <div><dt>Data / difficulty</dt><dd>{profile.data_constraints} · {profile.preferred_difficulty}</dd></div>
        <div><dt>Preferred topics</dt><dd>{profile.preferred_topics.join(", ") || "None stated"}</dd></div>
        <div><dt>Avoid topics</dt><dd>{profile.avoid_topics.join(", ") || "None stated"}</dd></div>
        <div><dt>Retrieval</dt><dd>{profile.retrieval_mode.replaceAll("_", " ")} · top {profile.top_k}</dd></div>
      </dl>
      <p className="section-kicker">This profile is displayed from client memory and is not a saved account or student record.</p>
    </article>
  );
}

function EvidenceOnlyResults({ response, papers, onSelectPaper }: { response: SearchResponse; papers: Paper[]; onSelectPaper: (paperId: string) => void }) {
  return (
    <section className="evidence-baseline" aria-labelledby="evidence-baseline-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Non-generative comparison</p>
          <h2 id="evidence-baseline-title">Evidence-only ranked papers and passages</h2>
        </div>
      </div>
      <p className="notice">This baseline returns retrieval evidence only. It does not invent an extension, estimate feasibility, or assign a supervisor.</p>
      {response.warnings.length ? <p className="notice notice--warning">{response.warnings.join(" ")}</p> : null}
      <div className="paper-list">
        {response.results.map((result) => (
          <article className="citation-card" key={result.chunk_id}>
            <div className="paper-card__meta">
              <span>Passage rank {result.rank}</span>
              <span>{result.section ?? "Unknown section"}</span>
              <span>Pages {result.page_start ?? "?"}-{result.page_end ?? "?"}</span>
              <span>Chunk {result.chunk_id}</span>
            </div>
            <h3>{result.paper_title}</h3>
            <p>{result.snippet}</p>
            {papers.some((paper) => paper.paper_id === result.paper_id) ? <button className="link-button" onClick={() => onSelectPaper(result.paper_id)}>Paper detail</button> : null}
          </article>
        ))}
        {!response.results.length ? <EmptyState title="No evidence-only results" body="Broaden the profile terms or choose an index mode that is ready for the current corpus." /> : null}
      </div>
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
          <h4>System Fit Rationale</h4>
          <p>{recommendation.why_it_fits_student}</p>
        </section>
        <section>
          <h4>Paper Focus (evidence-derived)</h4>
          <p>{recommendation.paper_focus}</p>
        </section>
        <section>
          <h4>Gap Status ({recommendation.identified_gap.support_status.replaceAll("_", " ")})</h4>
          <p>{recommendation.identified_gap.text}</p>
        </section>
        <section>
          <h4>System-Suggested Extension</h4>
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

      {recommendation.difficulty === "unknown" ? (
        <p className="notice notice--warning" role="status">Difficulty could not be inferred from the available source evidence. Treat feasibility as unverified until a supervisor or domain expert checks the scope.</p>
      ) : null}

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
              <p className="paper-card__status">Source snippet: {fact.snippet}</p>
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
          <summary>Related work (evidence-derived)</summary>
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
          <summary>Potential researcher fit (discovery aid, not supervisor assignment)</summary>
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

function profileQuery(profile: ExtensionFinderRequest): string {
  return [
    profile.interests,
    profile.preferred_topics.join(" "),
    profile.project_type,
    profile.data_constraints,
  ].filter(Boolean).join(" ");
}
