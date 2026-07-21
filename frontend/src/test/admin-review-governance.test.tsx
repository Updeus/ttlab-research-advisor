import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { setReviewerToken } from "../api/client";
import { AdminReviewPage } from "../pages/AdminReviewPage";
import { json, paper } from "./fixtures";

const overview = {
  papers_total: 1,
  papers_needing_metadata_review: 1,
  papers_missing_pdfs: 0,
  papers_with_extraction_failures: 0,
  possible_scanned_pdfs: 1,
  total_chunks: 1,
  rag_answers: {},
  rag_answers_by_grounding: {},
  thesis_recommendations: {},
  thesis_recommendations_by_grounding: {},
  paper_artifacts: {},
  paper_artifacts_by_grounding: {},
  paper_artifacts_by_type: {},
  artifacts_needing_review: 1,
  total_review_events: 51,
  recent_review_events: [],
};

const syncStatus = {
  source: "ttlab",
  enabled: false,
  schedule: "0 2 * * *",
  timezone: "America/La_Paz",
  run_on_startup: false,
  worker_poll_seconds: 30,
  download_pdfs: true,
  dense_index_policy: "if_present",
  manual_trigger_allowed: true,
  running: false,
  manual_request_pending: false,
  manual_requested_at: null,
  manual_requested_by: null,
  last_success_at: null,
  last_failure_at: null,
  next_scheduled_at: null,
  last_run: null,
  recent_runs: [],
};

const publicationPreview = {
  surface: "local_review_preview",
  public: false,
  notice: "Protected reviewer preview.",
  items: [{
    ...paper,
    publication_status: "pending_review",
    rights_status: "unknown",
    public_access_level: "hidden",
    corpus_eligibility_status: "excluded",
    corpus_exclusion_reason: "ocr_review_required",
    possible_scanned_pdf: true,
    extraction_content_type: "scanned_pdf",
    ocr_status: "completed",
    ocr_provider: "tesseract",
    ocr_provider_version: "5.4",
    ocr_pages_count: 4,
    ocr_review_required: true,
    reviewer_notes: "Metadata review note must stay separate",
    extraction_review_status: "needs_review",
    extraction_reviewer_notes: "Inspect the raster OCR output",
    pdf_title_match_status: "mismatch",
    pdf_title_match_score: 0.42,
  }],
};

const serviceCapabilities = {
  actor: { actor_id: "local-demo", role: "admin", reviewer_type: "service", local_demo_bypass: true },
  capabilities: {
    review: true,
    save_corrections: true,
    approve_or_reject: false,
    set_publication_and_rights: false,
    trigger_ingestion: true,
  },
  allowed_review_transitions: {
    needs_review: ["needs_review", "needs_reprocess"],
    ai_reviewed: ["needs_review", "needs_reprocess"],
    reviewed: ["needs_review", "needs_reprocess"],
    approved: ["needs_review", "needs_reprocess"],
    rejected: ["needs_review", "needs_reprocess"],
    needs_reprocess: ["needs_review", "needs_reprocess"],
  },
};

const humanCapabilities = {
  ...serviceCapabilities,
  actor: { actor_id: "human-admin", role: "admin", reviewer_type: "human", local_demo_bypass: false },
  capabilities: { ...serviceCapabilities.capabilities, approve_or_reject: true, set_publication_and_rights: true },
  allowed_review_transitions: {
    ...serviceCapabilities.allowed_review_transitions,
    needs_review: ["needs_review", "reviewed", "approved", "rejected", "needs_reprocess"],
  },
};

function baseResponse(path: string, capabilities = serviceCapabilities) {
  if (path === "/api/admin/overview") return json(overview);
  if (path === "/api/admin/publication-preview/papers") return json(publicationPreview);
  if (path === "/api/admin/capabilities") return json(capabilities);
  if (path === "/api/admin/ingestion-sync") return json(syncStatus);
  return null;
}

function artifactQueueItem() {
  return {
    item_type: "paper_artifact",
    item_id: "artifact-1",
    title: "Public summary",
    label: "Public summary",
    status: "needs_review",
    grounding_status: "grounded",
    warnings: [],
    created_at: "2026-07-20T12:00:00Z",
    updated_at: "2026-07-20T12:00:00Z",
    frontend_link: "/admin",
    details: {
      generated_text: "Original generated output",
      generated_json: { summary: "Original generated structure" },
      corrected_text: "Reviewer correction v1",
      corrected_json: { summary: "Reviewer corrected structure" },
      reviewer_notes: "Check terminology",
      citations: [],
    },
  };
}

describe("admin governance and completeness", () => {
  afterEach(() => setReviewerToken(""));

  it("shows only server-permitted transitions and exposes full extraction diagnostics", async () => {
    const user = userEvent.setup();
    setReviewerToken("a".repeat(32));
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = new URL(String(input));
      const common = baseResponse(url.pathname);
      if (common) return common;
      if (url.pathname === "/api/admin/review-queue") return json({ total: 0, limit: 50, offset: 0, items: [] });
      if (url.pathname === "/api/admin/review-events") return json({ total: 0, limit: 50, offset: 0, items: [] });
      return json({ detail: `Unhandled ${url.pathname}` }, { status: 404 });
    });

    render(<AdminReviewPage papers={[]} onSelectPaper={vi.fn()} />);
    expect(await screen.findByText(/service admin/)).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Extraction Review" }));

    expect(screen.getByText("tesseract")).toBeInTheDocument();
    expect(screen.getByText("5.4")).toBeInTheDocument();
    expect(screen.getByText("ocr_review_required")).toBeInTheDocument();
    expect(screen.getByLabelText("Reviewer notes")).toHaveValue("Inspect the raster OCR output");
    expect(screen.getByRole("button", { name: "Needs Reprocess" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reject" })).not.toBeInTheDocument();
  });

  it("shows publication controls only to a human admin and records the three independent decisions", async () => {
    const user = userEvent.setup();
    const requests: Array<Record<string, unknown>> = [];
    setReviewerToken("a".repeat(32));
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = new URL(String(input));
      const common = baseResponse(url.pathname, humanCapabilities);
      if (common) return common;
      if (url.pathname === "/api/admin/review-queue") return json({ total: 0, limit: 50, offset: 0, items: [] });
      if (url.pathname === "/api/admin/review-events") return json({ total: 0, limit: 50, offset: 0, items: [] });
      if (url.pathname === `/api/admin/papers/${paper.paper_id}/publication` && init?.method === "PATCH") {
        requests.push(JSON.parse(String(init.body)));
        return json({ paper: publicationPreview.items[0], review_event: {} });
      }
      return json({ detail: `Unhandled ${url.pathname}` }, { status: 404 });
    });

    render(<AdminReviewPage papers={[]} onSelectPaper={vi.fn()} />);
    await screen.findByText(/human admin/);
    await user.click(screen.getByRole("tab", { name: "Publication Preview" }));
    await user.selectOptions(screen.getByLabelText("Editorial publication status"), "published");
    await user.selectOptions(screen.getByLabelText("PDF/content rights status"), "cleared");
    await user.selectOptions(screen.getByLabelText("Public access level"), "metadata_only");
    await user.type(screen.getByLabelText("Decision notes"), "Verified by the authorized human administrator");
    await user.click(screen.getByRole("button", { name: "Save publication decision" }));

    await waitFor(() => expect(requests).toEqual([{
      publication_status: "published",
      rights_status: "cleared",
      public_access_level: "metadata_only",
      reviewer_notes: "Verified by the authorized human administrator",
    }]));
  });

  it("saves corrections separately, refreshes shared state, and clears a stale selected item", async () => {
    const user = userEvent.setup();
    const onDataChanged = vi.fn();
    let movedOutOfQueue = false;
    const requests: Array<{ path: string; body: Record<string, unknown> }> = [];
    setReviewerToken("a".repeat(32));
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = new URL(String(input));
      const common = baseResponse(url.pathname);
      if (common) return common;
      if (url.pathname === "/api/admin/review-queue") {
        return json({ total: movedOutOfQueue ? 0 : 1, limit: 50, offset: 0, items: movedOutOfQueue ? [] : [artifactQueueItem()] });
      }
      if (url.pathname === "/api/admin/review-events") return json({ total: 0, limit: 50, offset: 0, items: [] });
      if (url.pathname === "/api/admin/artifacts/artifact-1/correction" && init?.method === "PATCH") {
        requests.push({ path: url.pathname, body: JSON.parse(String(init.body)) });
        return json({ artifact: {}, review_event: {} });
      }
      if (url.pathname === "/api/admin/artifacts/artifact-1/review" && init?.method === "PATCH") {
        requests.push({ path: url.pathname, body: JSON.parse(String(init.body)) });
        movedOutOfQueue = true;
        return json({ artifact: {}, review_event: {} });
      }
      return json({ detail: `Unhandled ${url.pathname}` }, { status: 404 });
    });

    render(<AdminReviewPage papers={[]} onSelectPaper={vi.fn()} onDataChanged={onDataChanged} />);
    await screen.findByText(/service admin/);
    await user.click(screen.getByRole("tab", { name: "Artifacts" }));
    const correction = screen.getByLabelText("Reviewer-corrected text");
    expect(correction).toHaveValue("Reviewer correction v1");
    await user.clear(correction);
    await user.type(correction, "Reviewer correction v2");
    await user.click(screen.getByRole("button", { name: "Save Correction (returns to needs review)" }));

    await waitFor(() => expect(requests[0]).toEqual({
      path: "/api/admin/artifacts/artifact-1/correction",
      body: { corrected_text: "Reviewer correction v2", reviewer_notes: "Check terminology" },
    }));
    expect(requests[0].body).not.toHaveProperty("review_status");

    await user.click(screen.getByRole("button", { name: "Needs Reprocess" }));
    await waitFor(() => expect(requests[1]).toEqual({
      path: "/api/admin/artifacts/artifact-1/review",
      body: { review_status: "needs_reprocess", reviewer_notes: "Check terminology" },
    }));
    expect(requests[1].body).not.toHaveProperty("corrected_text");
    expect(await screen.findByText("No paper artifact selected")).toBeInTheDocument();
    expect(onDataChanged).toHaveBeenCalledTimes(2);
  });

  it("locks every decision and correction control while an item mutation is pending", async () => {
    const user = userEvent.setup();
    let reviewRequestCount = 0;
    let correctionRequestCount = 0;
    let resolveReview: ((response: Response) => void) | undefined;
    let resolveCorrection: ((response: Response) => void) | undefined;
    const pendingReview = new Promise<Response>((resolve) => {
      resolveReview = resolve;
    });
    const pendingCorrection = new Promise<Response>((resolve) => {
      resolveCorrection = resolve;
    });
    setReviewerToken("a".repeat(32));
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = new URL(String(input));
      const common = baseResponse(url.pathname, humanCapabilities);
      if (common) return common;
      if (url.pathname === "/api/admin/review-queue") return json({ total: 1, limit: 50, offset: 0, items: [artifactQueueItem()] });
      if (url.pathname === "/api/admin/review-events") return json({ total: 0, limit: 50, offset: 0, items: [] });
      if (url.pathname === "/api/admin/artifacts/artifact-1/review" && init?.method === "PATCH") {
        reviewRequestCount += 1;
        return pendingReview;
      }
      if (url.pathname === "/api/admin/artifacts/artifact-1/correction" && init?.method === "PATCH") {
        correctionRequestCount += 1;
        return pendingCorrection;
      }
      return json({ detail: `Unhandled ${url.pathname}` }, { status: 404 });
    });

    render(<AdminReviewPage papers={[]} onSelectPaper={vi.fn()} />);
    await screen.findByText(/human admin/);
    await user.click(screen.getByRole("tab", { name: "Artifacts" }));
    const correctionEditor = screen.getByLabelText("Reviewer-corrected text");
    await user.clear(correctionEditor);
    await user.type(correctionEditor, "A pending corrected version");
    const correctionButton = screen.getByRole("button", { name: "Save Correction (returns to needs review)" });
    expect(correctionButton).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "Mark Reviewed" }));
    await waitFor(() => expect(reviewRequestCount).toBe(1));

    expect(screen.getByRole("button", { name: "Mark Reviewed..." })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Needs Reprocess" })).toBeDisabled();
    expect(correctionButton).toBeDisabled();
    expect(correctionEditor).toBeDisabled();
    expect(screen.getByLabelText("Reviewer notes")).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    fireEvent.click(correctionButton);
    expect(reviewRequestCount).toBe(1);
    expect(correctionRequestCount).toBe(0);

    resolveReview?.(await json({ artifact: {}, review_event: {} }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled());

    const refreshedEditor = screen.getByLabelText("Reviewer-corrected text");
    await user.clear(refreshedEditor);
    await user.type(refreshedEditor, "A second pending correction");
    await user.click(screen.getByRole("button", { name: "Save Correction (returns to needs review)" }));
    await waitFor(() => expect(correctionRequestCount).toBe(1));

    expect(screen.getByRole("button", { name: "Saving correction..." })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Mark Reviewed" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Needs Reprocess" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    fireEvent.click(screen.getByRole("button", { name: "Needs Reprocess" }));
    expect(reviewRequestCount).toBe(1);

    resolveCorrection?.(await json({ artifact: {}, review_event: {} }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled());
  });

  it("pages review queue and append-only event history without truncating totals", async () => {
    const user = userEvent.setup();
    const requestedUrls: string[] = [];
    setReviewerToken("a".repeat(32));
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = new URL(String(input));
      requestedUrls.push(url.href);
      const common = baseResponse(url.pathname, humanCapabilities);
      if (common) return common;
      if (url.pathname === "/api/admin/review-queue") {
        const offset = Number(url.searchParams.get("offset") ?? 0);
        return json({ total: 51, limit: 50, offset, items: [artifactQueueItem()] });
      }
      if (url.pathname === "/api/admin/review-events") {
        const offset = Number(url.searchParams.get("offset") ?? 0);
        return json({
          total: 51,
          limit: 50,
          offset,
          items: [{
            review_event_id: `event-${offset}`,
            item_type: "paper_artifact",
            item_id: "artifact-1",
            action: "reviewed",
            previous_status: "needs_review",
            new_status: "reviewed",
            reviewer_name: "Human Admin",
            reviewer_type: "human",
            reviewer_role: "admin",
            reviewer_notes: null,
            diff: {},
            created_at: "2026-07-20T12:00:00Z",
          }],
        });
      }
      return json({ detail: `Unhandled ${url.pathname}` }, { status: 404 });
    });

    render(<AdminReviewPage papers={[]} onSelectPaper={vi.fn()} />);
    await screen.findByText(/human admin/);
    await user.click(screen.getByRole("tab", { name: "Review Queue" }));
    const queuePagination = screen.getByRole("navigation", { name: "Review queue pagination" });
    expect(within(queuePagination).getByText("Showing 1–50 of 51")).toBeInTheDocument();
    await user.click(within(queuePagination).getByRole("button", { name: "Next" }));
    expect(await within(queuePagination).findByText("Showing 51–51 of 51")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Review Events" }));
    const eventPagination = screen.getByRole("navigation", { name: "Review events pagination" });
    await user.click(within(eventPagination).getByRole("button", { name: "Next" }));
    expect(await within(eventPagination).findByText("Showing 51–51 of 51")).toBeInTheDocument();
    expect(requestedUrls.some((url) => url.includes("/api/admin/review-queue") && url.includes("offset=50"))).toBe(true);
    expect(requestedUrls.some((url) => url.includes("/api/admin/review-events") && url.includes("offset=50"))).toBe(true);
  });

  it("shows original, corrected, and complete recommendation fields", async () => {
    const user = userEvent.setup();
    const recommendation = {
      extension_title: "Generated Extension",
      paper_title: paper.title,
      why_it_fits_student: "Generated fit",
      extension_summary: "Generated summary",
      risk_level: "medium",
      data_availability: "public",
      implementation_time: "semester",
      mvp_scope: "Generated MVP",
      stretch_goals: ["Stretch"],
      required_skills: ["Python"],
      evaluation_plan: "Measure Recall@5",
      citations: [],
    };
    const corrected = { ...recommendation, extension_title: "Corrected Extension", risk_level: "low" };
    const item = {
      ...artifactQueueItem(),
      item_type: "thesis_recommendation",
      item_id: "recommendation-1",
      title: "Recommendation run",
      details: {
        request: { interests: "retrieval" },
        recommendations: [recommendation],
        corrected_recommendations_json: { items: [corrected] },
        effective_provenance: { available: false, source: null },
        reviewer_notes: "",
      },
    };
    setReviewerToken("a".repeat(32));
    const requests: Array<Record<string, unknown>> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = new URL(String(input));
      const common = baseResponse(url.pathname, humanCapabilities);
      if (common) return common;
      if (url.pathname === "/api/admin/review-queue") return json({ total: 1, limit: 50, offset: 0, items: [item] });
      if (url.pathname === "/api/admin/review-events") return json({ total: 0, limit: 50, offset: 0, items: [] });
      if (url.pathname === "/api/admin/recommendations/recommendation-1/correction" && init?.method === "PATCH") {
        requests.push(JSON.parse(String(init.body)));
        return json({ recommendation: {}, review_event: {} });
      }
      return json({ detail: `Unhandled ${url.pathname}` }, { status: 404 });
    });

    render(<AdminReviewPage papers={[]} onSelectPaper={vi.fn()} />);
    await screen.findByText(/human admin/);
    await user.click(screen.getByRole("tab", { name: "Recommendations" }));

    expect(screen.getByRole("heading", { name: "Corrected Extension" })).toBeInTheDocument();
    expect(screen.getByText("Reviewer-corrected recommendation fields").parentElement).toHaveTextContent("Corrected Extension");
    expect(screen.getByText("All recommendation fields").parentElement).toHaveTextContent("evaluation_plan");
    expect(screen.getByText("All recommendation fields").parentElement).toHaveTextContent("implementation_time");
    expect(screen.getByText("Original generated recommendation fields").parentElement).toHaveTextContent("Generated Extension");

    const editor = screen.getByLabelText("Reviewer-corrected recommendation JSON");
    fireEvent.change(editor, { target: { value: JSON.stringify([{ ...corrected, extension_title: "Second Correction" }]) } });
    await user.click(screen.getByRole("button", { name: "Save Recommendation Correction (returns to needs review)" }));
    await waitFor(() => expect(requests[0]).toEqual({
      corrected_recommendations_json: [{ ...corrected, extension_title: "Second Correction" }],
    }));
  });
});
