import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { App } from "../App";
import { installBaseFetchMock, json, paper } from "./fixtures";

describe("route-based application shell", () => {
  beforeEach(() => {
    installBaseFetchMock();
  });

  it("deep-links, updates title, exposes current navigation, and restores focus", async () => {
    render(<MemoryRouter initialEntries={["/papers"]}><App /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "Paper Browser" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Papers/ })).toHaveAttribute("aria-current", "page");
    expect(document.title).toBe("Paper Browser | TTLAB Research Intelligence");
    await waitFor(() => expect(document.activeElement).toHaveAttribute("id", "main-content"));
    expect(screen.getByRole("link", { name: "Skip to main content" })).toHaveAttribute("href", "#main-content");
  });

  it("loads a paper detail route without prior in-app selection", async () => {
    render(<MemoryRouter initialEntries={["/papers/paper-1"]}><App /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "Grounded Research Discovery" })).toBeInTheDocument();
    expect(await screen.findByText("A source-grounded passage.")).toBeInTheDocument();
    expect(screen.getByText("Generation requires a reviewer credential.")).toBeInTheDocument();
  });

  it("loads a direct paper record when the shared publication catalogue is unavailable", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    const baseImplementation = fetchMock.getMockImplementation();
    expect(baseImplementation).toBeDefined();
    fetchMock.mockImplementation((input, init) => {
      const raw = typeof input === "string" ? input : input instanceof URL ? input.href : (input as Request).url;
      const url = new URL(raw, "http://127.0.0.1:8000");
      if (url.pathname === "/api/papers") {
        return json({ detail: "Catalogue unavailable" }, { status: 503 });
      }
      if (url.pathname === "/api/papers/paper-1") {
        return json(paper);
      }
      return baseImplementation!(input, init);
    });

    render(<MemoryRouter initialEntries={["/papers/paper-1"]}><App /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "Publication catalogue unavailable" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Grounded Research Discovery" })).toBeInTheDocument();
    expect(await screen.findByText("A source-grounded passage.")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/api/papers/paper-1"))).toBe(true);
  });

  it("makes artifact generation available through the explicit local-demo bypass", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.mocked(globalThis.fetch);
    const baseImplementation = fetchMock.getMockImplementation();
    expect(baseImplementation).toBeDefined();
    fetchMock.mockImplementation((input, init) => {
      const raw = typeof input === "string" ? input : input instanceof URL ? input.href : (input as Request).url;
      const url = new URL(raw, "http://127.0.0.1:8000");
      if (url.pathname === "/") {
        return json({
          service: "TTLAB Research Intelligence Platform",
          status: "ok",
          security_mode: "local_demo",
          admin_authentication: "insecure_local_demo_bypass",
          frontend: "http://127.0.0.1:5173",
          api_docs: "/docs",
          health: "/health",
          readiness: "/ready",
        });
      }
      if (url.pathname === "/api/papers/paper-1/artifacts/generate" && init?.method === "POST") {
        return json({ paper_id: "paper-1", artifacts: [], grounding_status: "unsupported", warnings: [] });
      }
      return baseImplementation!(input, init);
    });

    render(<MemoryRouter initialEntries={["/papers/paper-1"]}><App /></MemoryRouter>);
    const generate = await screen.findByRole("button", { name: "Generate Artifacts" });
    await waitFor(() => expect(generate).toBeEnabled());
    await user.click(generate);
    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/artifacts/generate"))).toBe(true));
    const request = fetchMock.mock.calls.find(([input]) => String(input).includes("/artifacts/generate"));
    expect(JSON.parse(String(request?.[1]?.body))).toMatchObject({ overwrite: false });
  });

  it("protects administration with local login and keeps credentials out of web storage", async () => {
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/admin"]}><App /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "Administrator sign in" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("Username"), "jarod");
    await user.type(screen.getByLabelText("Password"), "a private password");
    expect(screen.queryByRole("link", { name: /Admin Control/ })).not.toBeInTheDocument();
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });

  it("provides a deterministic 404 route", async () => {
    render(<MemoryRouter initialEntries={["/does-not-exist"]}><App /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "Page not found" })).toBeInTheDocument();
    expect(document.title).toBe("Page Not Found | TTLAB Research Intelligence");
  });

  it("keeps independent routes usable when the publication catalogue fails", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    const baseImplementation = fetchMock.getMockImplementation();
    expect(baseImplementation).toBeDefined();
    fetchMock.mockImplementation((input, init) => {
      const raw = typeof input === "string" ? input : input instanceof URL ? input.href : (input as Request).url;
      if (new URL(raw, "http://127.0.0.1:8000").pathname === "/api/papers") {
        return json({ detail: "Catalogue unavailable" }, { status: 503 });
      }
      return baseImplementation!(input, init);
    });

    render(<MemoryRouter initialEntries={["/search"]}><App /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "Publication catalogue unavailable" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Search Source Chunks" })).toBeInTheDocument();
    expect(screen.getByText(/Independent routes remain available/)).toBeInTheDocument();
  });

  it("uses explorer routes as the only detail trigger and exposes current subnavigation", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.mocked(globalThis.fetch);
    const baseImplementation = fetchMock.getMockImplementation();
    expect(baseImplementation).toBeDefined();
    let topicDetailRequests = 0;
    const topic = {
      topic_id: "retrieval",
      name: "Retrieval",
      normalized_name: "retrieval",
      description: "Source-derived retrieval topic.",
      paper_count: 1,
      author_count: 1,
      top_authors: [],
      sample_papers: [],
      review_status: "needs_review",
    };
    fetchMock.mockImplementation((input, init) => {
      const raw = typeof input === "string" ? input : input instanceof URL ? input.href : (input as Request).url;
      const url = new URL(raw, "http://127.0.0.1:8000");
      if (url.pathname === "/api/topics") return json({ total: 1, limit: 50, offset: 0, items: [topic] });
      if (url.pathname === "/api/topics/retrieval") {
        topicDetailRequests += 1;
        return json({ ...topic, papers: [], authors: [], related_topics: [] });
      }
      return baseImplementation!(input, init);
    });

    render(<MemoryRouter initialEntries={["/explorer/topics"]}><App /></MemoryRouter>);
    const topicsLink = await screen.findByRole("link", { name: "Topics" });
    expect(topicsLink).toHaveAttribute("aria-current", "page");
    const openTopic = await screen.findByRole("button", { name: "Open Topic" });
    openTopic.focus();
    await user.keyboard("{Enter}");
    await waitFor(() => expect(screen.getAllByRole("heading", { name: "Retrieval" })).toHaveLength(2));
    expect(screen.getByRole("link", { name: "Topics" })).toHaveAttribute("aria-current", "page");
    expect(topicDetailRequests).toBe(1);
  });

  it("pages through the complete public author result set", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.mocked(globalThis.fetch);
    const baseImplementation = fetchMock.getMockImplementation();
    expect(baseImplementation).toBeDefined();
    fetchMock.mockImplementation((input, init) => {
      const raw = typeof input === "string" ? input : input instanceof URL ? input.href : (input as Request).url;
      const url = new URL(raw, "http://127.0.0.1:8000");
      if (url.pathname === "/api/authors") {
        const offset = Number(url.searchParams.get("offset") ?? 0);
        const count = offset === 0 ? 50 : 1;
        return json({
          total: 51,
          limit: 50,
          offset,
          items: Array.from({ length: count }, (_, index) => ({
            author_id: offset + index + 1,
            name: `Author ${offset + index + 1}`,
            paper_count: 1,
            top_topics: [],
            recent_papers: [],
            coauthor_count: 0,
            review_status: "reviewed",
          })),
        });
      }
      return baseImplementation!(input, init);
    });

    render(<MemoryRouter initialEntries={["/explorer/authors"]}><App /></MemoryRouter>);
    expect(await screen.findByText("Showing 1–50 of 51 authors")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("Showing 51–51 of 51 authors")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Author 51" })).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/api/authors?limit=50&offset=50"))).toBe(true);
  });

  it("pages through the complete public topic result set", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.mocked(globalThis.fetch);
    const baseImplementation = fetchMock.getMockImplementation();
    expect(baseImplementation).toBeDefined();
    fetchMock.mockImplementation((input, init) => {
      const raw = typeof input === "string" ? input : input instanceof URL ? input.href : (input as Request).url;
      const url = new URL(raw, "http://127.0.0.1:8000");
      if (url.pathname === "/api/topics") {
        const offset = Number(url.searchParams.get("offset") ?? 0);
        const count = offset === 0 ? 50 : 1;
        return json({
          total: 51,
          limit: 50,
          offset,
          items: Array.from({ length: count }, (_, index) => ({
            topic_id: `topic-${offset + index + 1}`,
            name: `Topic ${offset + index + 1}`,
            normalized_name: `topic ${offset + index + 1}`,
            description: "Source-derived topic candidate.",
            paper_count: 1,
            author_count: 1,
            top_authors: [],
            sample_papers: [],
            review_status: "reviewed",
          })),
        });
      }
      return baseImplementation!(input, init);
    });

    render(<MemoryRouter initialEntries={["/explorer/topics"]}><App /></MemoryRouter>);
    expect(await screen.findByText("Showing 1–50 of 51 topics")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("Showing 51–51 of 51 topics")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Topic 51" })).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/api/topics?limit=50&offset=50"))).toBe(true);
  });
});
