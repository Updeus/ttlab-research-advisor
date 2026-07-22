import { useEffect, useRef, useState } from "react";
import { RefreshCw, Sparkles } from "lucide-react";

import { ApiError, fetchLocalLlms, generateIdeas, isAbortError } from "../api/client";
import { InlineProgress } from "../components/UiPrimitives";
import type { ToastTone } from "../components/UiPrimitives";
import type {
  IdeaChatMessage,
  IdeaGenerationResponse,
  LocalLlmStatus,
  Paper,
} from "../types/paper";

type IdeaGeneratorPageProps = {
  papers: Paper[];
  onSelectPaper: (paperId: string) => void;
  onNotify?: (message: string, tone?: ToastTone) => void;
};

type ChatTurn =
  | { id: string; role: "user"; content: string }
  | { id: string; role: "assistant"; content: string; response: IdeaGenerationResponse };

const STARTER_PROMPTS = [
  "I am interested in AI and agriculture and I know Python. What thesis ideas could I explore?",
  "I want to build a useful web application in one semester. Help me find a research direction.",
  "I like data science but I am not sure what problem to study. Give me a few practical starting points.",
];

export function IdeaGeneratorPage({ papers, onSelectPaper, onNotify }: IdeaGeneratorPageProps) {
  const [draft, setDraft] = useState("");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [status, setStatus] = useState<LocalLlmStatus | null>(null);
  const [statusLoading, setStatusLoading] = useState(true);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [generationError, setGenerationError] = useState<string | null>(null);
  const [pendingMessage, setPendingMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const requestController = useRef<AbortController | null>(null);
  const sequence = useRef(0);
  const composerRef = useRef<HTMLTextAreaElement>(null);

  function loadStatus() {
    setStatusLoading(true);
    setStatusError(null);
    fetchLocalLlms()
      .then(setStatus)
      .catch((error: unknown) => {
        setStatus(null);
        setStatusError(error instanceof Error ? error.message : "Ollama status is unavailable.");
      })
      .finally(() => setStatusLoading(false));
  }

  useEffect(() => {
    loadStatus();
    return () => requestController.current?.abort();
  }, []);

  const ollamaReady = Boolean(status?.generation_available ?? status?.available);
  const defaultModel = status?.default_model && status.default_model !== "none"
    ? status.default_model
    : "approved default model";

  function submit() {
    const message = draft.trim();
    if (!message) {
      setGenerationError("Describe an interest, problem, skill, or possible project direction.");
      composerRef.current?.focus();
      return;
    }
    if (!ollamaReady) {
      setGenerationError("Ollama is not ready. Check the local service and retry its status first.");
      return;
    }

    requestController.current?.abort();
    const controller = new AbortController();
    requestController.current = controller;
    const requestNumber = ++sequence.current;
    const history = transcript(turns).slice(-12);
    setLoading(true);
    setPendingMessage(message);
    setGenerationError(null);

    generateIdeas({ message, history }, controller.signal)
      .then((response) => {
        if (requestNumber !== sequence.current) return;
        setTurns((current) => [
          ...current,
          { id: `user-${response.message_id}`, role: "user", content: message },
          { id: response.message_id, role: "assistant", content: assistantHistoryText(response), response },
        ]);
        setDraft("");
        onNotify?.(
          `Generated ${response.ideas.length} thesis ${response.ideas.length === 1 ? "idea" : "ideas"} with ${response.citations.length} related source ${response.citations.length === 1 ? "passage" : "passages"}.`,
          response.paper_match_status === "matched" ? "success" : "info",
        );
      })
      .catch((error: unknown) => {
        if (requestNumber !== sequence.current || isAbortError(error)) return;
        const unavailable = error instanceof ApiError && [502, 503].includes(error.status);
        const messageText = error instanceof Error ? error.message : "Idea generation failed.";
        setGenerationError(messageText);
        if (unavailable) setStatus((current) => current ? { ...current, generation_available: false } : current);
        onNotify?.(messageText, "error");
      })
      .finally(() => {
        if (requestNumber === sequence.current) {
          setLoading(false);
          setPendingMessage(null);
        }
      });
  }

  function newConversation() {
    requestController.current?.abort();
    sequence.current += 1;
    setTurns([]);
    setDraft("");
    setLoading(false);
    setPendingMessage(null);
    setGenerationError(null);
    composerRef.current?.focus();
  }

  return (
    <section className="page-section idea-generator" aria-labelledby="idea-generator-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Ollama-only student ideation</p>
          <h2 id="idea-generator-title">Idea Generator</h2>
        </div>
        {turns.length ? <button className="action-button action-button--secondary" onClick={newConversation}>New conversation</button> : null}
      </div>

      <p className="notice notice--warning">
        These are generated candidate directions, not claims of novelty, guaranteed feasibility, or supervisor approval. Related papers provide background or inspiration; they do not prove that an idea is new.
      </p>
      <p className="notice">
        Privacy: this conversation stays in page memory and is sent only with the current request. Refreshing or choosing New conversation clears it. Do not enter confidential or personal data.
      </p>

      <div className="llm-model-strip" role="status" aria-live="polite">
        <span className={`llm-signal llm-signal--${ollamaReady ? "green" : "red"}`}>
          {statusLoading ? "Checking" : ollamaReady ? "Ready" : "Unavailable"}
        </span>
        <strong>{defaultModel}</strong>
        <span>{ollamaReady ? "Approved local Ollama model" : "No approved Ollama model can generate right now"}</span>
        {!ollamaReady && !statusLoading ? (
          <button className="link-button" onClick={loadStatus}><RefreshCw size={15} aria-hidden="true" /> Retry status</button>
        ) : null}
      </div>
      {statusError ? <p className="notice notice--error" role="alert">{statusError}</p> : null}

      {!turns.length ? (
        <section className="idea-welcome" aria-labelledby="idea-welcome-title">
          <Sparkles size={28} aria-hidden="true" />
          <div>
            <h3 id="idea-welcome-title">Describe what interests you</h3>
            <p>Mention a topic, problem, skill, project type, or time constraint. The assistant will look for related TTLAB papers and will still help when no close paper matches.</p>
          </div>
          <div className="idea-starters" aria-label="Example prompts">
            {STARTER_PROMPTS.map((prompt) => (
              <button key={prompt} onClick={() => { setDraft(prompt); composerRef.current?.focus(); }}>{prompt}</button>
            ))}
          </div>
        </section>
      ) : null}

      <div className="idea-transcript" role="log" aria-live="polite" aria-label="Idea generation conversation">
        {turns.map((turn) => turn.role === "user" ? (
          <article className="chat-message chat-message--user" key={turn.id}>
            <p className="chat-message__role">You</p>
            <p>{turn.content}</p>
          </article>
        ) : (
          <AssistantTurn key={turn.id} response={turn.response} papers={papers} onSelectPaper={onSelectPaper} />
        ))}
        {pendingMessage ? (
          <article className="chat-message chat-message--user chat-message--pending">
            <p className="chat-message__role">You</p>
            <p>{pendingMessage}</p>
          </article>
        ) : null}
        {loading ? <InlineProgress label="Ollama is developing thesis directions" /> : null}
      </div>

      {generationError ? (
        <div className="notice notice--error" role="alert">
          <p>{generationError}</p>
          <button className="link-button" onClick={() => { loadStatus(); composerRef.current?.focus(); }}>Check Ollama and retry</button>
        </div>
      ) : null}

      <form className="idea-composer" onSubmit={(event) => { event.preventDefault(); submit(); }}>
        <label htmlFor="idea-message">What are you interested in doing?</label>
        <textarea
          ref={composerRef}
          id="idea-message"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="For example: I enjoy Python and climate data, and I need a semester-sized project..."
          rows={4}
          maxLength={2_000}
          disabled={loading}
          aria-describedby="idea-message-help"
        />
        <div className="idea-composer__actions">
          <small id="idea-message-help">The configured default Ollama model is used automatically. No other AI provider is called.</small>
          <button className="action-button" type="submit" disabled={loading || statusLoading || !ollamaReady || !draft.trim()}>
            <Sparkles size={16} aria-hidden="true" /> Generate ideas
          </button>
        </div>
      </form>
    </section>
  );
}

function AssistantTurn({ response, papers, onSelectPaper }: { response: IdeaGenerationResponse; papers: Paper[]; onSelectPaper: (paperId: string) => void }) {
  const paperInformed = response.citations.length > 0;
  return (
    <article className="chat-message chat-message--assistant">
      <div className="chat-message__heading">
        <p className="chat-message__role">Idea Generator</p>
        <span className={`idea-basis idea-basis--${paperInformed ? "paper" : "general"}`}>
          {paperInformed ? "Based on related TTLAB papers" : "General suggestion — no close database match"}
        </span>
      </div>
      <p>{response.reply}</p>
      <div className="idea-card-list">
        {response.ideas.map((idea, index) => (
          <section className="idea-card" key={`${response.message_id}-${idea.title}`}>
            <div className="idea-card__heading">
              <span>Idea {index + 1}</span>
              <span>{idea.basis === "paper_informed" ? "Paper-informed" : "General suggestion"}</span>
            </div>
            <h3>{idea.title}</h3>
            <p><strong>Research question:</strong> {idea.research_question}</p>
            <p>{idea.summary}</p>
            <dl>
              <div><dt>Why it may fit</dt><dd>{idea.why_it_fits}</dd></div>
              <div><dt>Minimum viable thesis</dt><dd>{idea.mvp_scope}</dd></div>
              <div><dt>Skills</dt><dd>{idea.skills.join(", ")}</dd></div>
              <div><dt>Evaluation</dt><dd>{idea.evaluation_plan}</dd></div>
            </dl>
          </section>
        ))}
      </div>
      {response.citations.length ? (
        <details className="retrieved-details">
          <summary>Related paper background ({response.citations.length})</summary>
          <div className="paper-list">
            {response.citations.map((citation) => (
              <article className="citation-card" key={citation.chunk_id}>
                <h3>{citation.title}</h3>
                <p>{citation.authors.join(", ") || "Authors need review"}{citation.year ? ` · ${citation.year}` : ""}</p>
                <p>{citation.snippet}</p>
                <p className="citation-locator">{citation.section || "Section unavailable"} · pages {citation.page_start ?? "?"}–{citation.page_end ?? "?"}</p>
                <div className="paper-card__actions">
                  {papers.some((paper) => paper.paper_id === citation.paper_id) ? <button className="link-button" onClick={() => onSelectPaper(citation.paper_id)}>Paper detail</button> : null}
                  {citation.source_url ? <a href={citation.source_url} target="_blank" rel="noreferrer">Source</a> : null}
                  {citation.pdf_url ? <a href={citation.pdf_url} target="_blank" rel="noreferrer">PDF</a> : null}
                </div>
              </article>
            ))}
          </div>
        </details>
      ) : null}
      {response.warnings.length ? (
        <details className="retrieved-details">
          <summary>Generation notes ({response.warnings.length})</summary>
          <ul>{response.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
        </details>
      ) : null}
      <p className="idea-model-note">Generated locally with {response.model}. Review the literature and discuss shortlisted ideas with a supervisor.</p>
    </article>
  );
}

function transcript(turns: ChatTurn[]): IdeaChatMessage[] {
  return turns.map((turn) => ({ role: turn.role, content: turn.content }));
}

function assistantHistoryText(response: IdeaGenerationResponse): string {
  const ideas = response.ideas.map((idea, index) => (
    `Idea ${index + 1}: ${idea.title}. ${idea.summary} MVP: ${idea.mvp_scope}`
  ));
  return [response.reply, ...ideas].join("\n").slice(0, 2_000);
}
