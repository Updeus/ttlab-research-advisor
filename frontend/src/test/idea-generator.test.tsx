import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { App } from "../App";
import { installBaseFetchMock, json, paper } from "./fixtures";

const readyStatus = {
  available: true,
  generation_available: true,
  base_url: "http://localhost:11434",
  default_model: "qwen-test:4b",
  model_count: 1,
  models: [{ name: "qwen-test:4b", installed: true, usable: true, source: "installed", color: "green", quality_tier: "test", rationale: "Test model", is_default: true }],
  candidate_pulls: [],
  recommended_pulls: [],
  benchmark: null,
  warnings: [],
  model_policy: "pinned_digest_only",
};

function ideaResponse({ matched = true } = {}) {
  return {
    message_id: matched ? "idea-message-1" : "idea-message-general",
    reply: matched ? "A related TTLAB paper gives you a useful starting point." : "No close paper match was found, but this is a practical direction to investigate.",
    paper_match_status: matched ? "matched" : "none",
    ideas: [{
      title: matched ? "Evaluate cited research discovery for students" : "Community climate data explorer",
      research_question: "How useful is a small evidence-aware tool for its intended users?",
      summary: "Build a focused prototype and evaluate it with a bounded question set.",
      why_it_fits: "It fits Python and web-development interests.",
      mvp_scope: "Build one workflow, one dataset, and one evaluation report.",
      skills: ["Python", "FastAPI"],
      evaluation_plan: "Measure task completion and review answer usefulness.",
      basis: matched ? "paper_informed" : "general_suggestion",
      source_chunk_ids: matched ? ["paper-1-0001"] : [],
    }],
    citations: matched ? [{
      paper_id: paper.paper_id,
      title: paper.title,
      authors: paper.authors,
      year: paper.year,
      chunk_id: "paper-1-0001",
      section: "Methodology",
      page_start: 2,
      page_end: 2,
      snippet: "A source-grounded passage about retrieval.",
      score: 0.8,
      source_url: paper.post_url,
      pdf_url: paper.pdf_url,
    }] : [],
    provider: "ollama",
    model: "qwen-test:4b",
    generation_metadata: {},
    runtime_provenance: {},
    warnings: matched ? [] : ["No close TTLAB paper match was established; the ideas are general model-generated suggestions."],
    created_at: "2026-07-22T00:00:00Z",
  };
}

describe("Ollama Idea Generator", () => {
  beforeEach(() => installBaseFetchMock());

  it("replaces the Finder route and renders paper-informed chat cards", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.mocked(globalThis.fetch);
    const base = fetchMock.getMockImplementation();
    expect(base).toBeDefined();
    let submittedBody: Record<string, unknown> | null = null;
    fetchMock.mockImplementation((input, init) => {
      const url = requestUrl(input);
      if (url.pathname === "/__missing_request__") return json({ detail: "Missing request" }, { status: 400 });
      if (url.pathname === "/api/llms/local") return json(readyStatus);
      if (url.pathname === "/api/recommendations/ideas" && init?.method === "POST") {
        submittedBody = JSON.parse(String(init.body));
        return json(ideaResponse());
      }
      return base!(input, init);
    });

    render(<MemoryRouter initialEntries={["/extensions"]}><App /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "Idea Generator" })).toBeInTheDocument();
    expect(screen.queryByText("Student Profile")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Idea Generator/ })).toHaveAttribute("aria-current", "page");

    await user.type(screen.getByLabelText("What are you interested in doing?"), "I know Python and want to work on RAG.");
    await user.click(screen.getByRole("button", { name: "Generate ideas" }));

    expect(await screen.findByRole("heading", { name: "Evaluate cited research discovery for students" })).toBeInTheDocument();
    expect(screen.getByText("Based on related TTLAB papers")).toBeInTheDocument();
    await user.click(screen.getByText("Related paper background (1)"));
    expect(screen.getByText("A source-grounded passage about retrieval.")).toBeInTheDocument();
    expect(submittedBody).toEqual({ message: "I know Python and want to work on RAG.", history: [] });
    expect(submittedBody).not.toHaveProperty("provider");
    expect(submittedBody).not.toHaveProperty("model");
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });

  it("sends bounded conversation context on a follow-up and can clear it", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.mocked(globalThis.fetch);
    const base = fetchMock.getMockImplementation();
    expect(base).toBeDefined();
    const bodies: Array<{ message: string; history: Array<{ role: string; content: string }> }> = [];
    fetchMock.mockImplementation((input, init) => {
      const url = requestUrl(input);
      if (url.pathname === "/__missing_request__") return json({ detail: "Missing request" }, { status: 400 });
      if (url.pathname === "/api/llms/local") return json(readyStatus);
      if (url.pathname === "/api/recommendations/ideas" && init?.method === "POST") {
        bodies.push(JSON.parse(String(init.body)));
        return json({ ...ideaResponse(), message_id: `idea-${bodies.length}` });
      }
      return base!(input, init);
    });

    render(<MemoryRouter initialEntries={["/extensions"]}><App /></MemoryRouter>);
    await screen.findByText("Approved local Ollama model");
    const composer = screen.getByLabelText("What are you interested in doing?");
    await user.type(composer, "I like research discovery.");
    await user.click(screen.getByRole("button", { name: "Generate ideas" }));
    await screen.findByText("A related TTLAB paper gives you a useful starting point.");
    await user.type(composer, "Make the first idea smaller for one semester.");
    await user.click(screen.getByRole("button", { name: "Generate ideas" }));
    await waitFor(() => expect(bodies).toHaveLength(2));

    expect(bodies[1].history).toHaveLength(2);
    expect(bodies[1].history[0]).toEqual({ role: "user", content: "I like research discovery." });
    expect(bodies[1].history[1].content).toContain("Idea 1: Evaluate cited research discovery for students");
    await user.click(screen.getByRole("button", { name: "New conversation" }));
    expect(screen.queryByText("A related TTLAB paper gives you a useful starting point.")).not.toBeInTheDocument();
  });

  it("labels unmatched responses as general suggestions", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.mocked(globalThis.fetch);
    const base = fetchMock.getMockImplementation();
    expect(base).toBeDefined();
    fetchMock.mockImplementation((input, init) => {
      const url = requestUrl(input);
      if (url.pathname === "/__missing_request__") return json({ detail: "Missing request" }, { status: 400 });
      if (url.pathname === "/api/llms/local") return json(readyStatus);
      if (url.pathname === "/api/recommendations/ideas" && init?.method === "POST") return json(ideaResponse({ matched: false }));
      return base!(input, init);
    });

    render(<MemoryRouter initialEntries={["/extensions"]}><App /></MemoryRouter>);
    await user.type(await screen.findByLabelText("What are you interested in doing?"), "I want to study marine archaeology.");
    await user.click(screen.getByRole("button", { name: "Generate ideas" }));

    expect(await screen.findByText("General suggestion — no close database match")).toBeInTheDocument();
    expect(screen.queryByText(/Related paper background/)).not.toBeInTheDocument();
  });

  it("shows an honest retry state and does not call generation when Ollama is unavailable", async () => {
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/extensions"]}><App /></MemoryRouter>);

    expect(await screen.findByText("No approved Ollama model can generate right now")).toBeInTheDocument();
    const composer = screen.getByLabelText("What are you interested in doing?");
    await user.type(composer, "Give me an idea.");
    expect(screen.getByRole("button", { name: "Generate ideas" })).toBeDisabled();
    expect(vi.mocked(globalThis.fetch).mock.calls.some(([input]) => requestUrl(input).pathname === "/api/recommendations/ideas")).toBe(false);
  });
});

function requestUrl(input: RequestInfo | URL | undefined): URL {
  if (!input) return new URL("/__missing_request__", "http://127.0.0.1:8000");
  const raw = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  return new URL(raw, "http://127.0.0.1:8000");
}
