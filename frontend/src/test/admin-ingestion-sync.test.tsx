import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { setReviewerToken } from "../api/client";
import { AdminReviewPage } from "../pages/AdminReviewPage";
import { json } from "./fixtures";

const overview = {
  papers_total: 1,
  papers_needing_metadata_review: 1,
  papers_missing_pdfs: 0,
  papers_with_extraction_failures: 0,
  possible_scanned_pdfs: 0,
  total_chunks: 4,
  rag_answers: {},
  rag_answers_by_grounding: {},
  thesis_recommendations: {},
  thesis_recommendations_by_grounding: {},
  paper_artifacts: {},
  paper_artifacts_by_grounding: {},
  paper_artifacts_by_type: {},
  artifacts_needing_review: 0,
  total_review_events: 0,
  recent_review_events: [],
};

const syncStatus = {
  source: "ttlab",
  enabled: true,
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
  next_scheduled_at: "2026-07-21T06:00:00Z",
  last_run: null,
  recent_runs: [],
};

describe("admin ingestion synchronization", () => {
  afterEach(() => setReviewerToken(""));

  it("shows the worker schedule and queues a protected manual run", async () => {
    const user = userEvent.setup();
    setReviewerToken("a".repeat(32));
    const notify = vi.fn();
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const raw = typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : (input as Request).url;
      const path = new URL(raw, "http://127.0.0.1:8000").pathname;
      if (path === "/api/admin/overview") return json(overview);
      if (path === "/api/admin/ingestion-sync" && init?.method !== "POST") return json(syncStatus);
      if (path === "/api/admin/review-queue") return json({ total: 0, limit: 50, offset: 0, items: [] });
      if (path === "/api/admin/review-events") return json([]);
      if (path === "/api/admin/ingestion-sync/request" && init?.method === "POST") {
        return json({
          accepted: true,
          message: "Synchronization request queued for the ingestion worker.",
          sync: { ...syncStatus, manual_request_pending: true, manual_requested_at: "2026-07-20T12:00:00Z" },
        }, { status: 202 });
      }
      return json({ detail: `Unhandled test endpoint ${path}` }, { status: 404 });
    });

    render(<AdminReviewPage papers={[]} onSelectPaper={vi.fn()} onNotify={notify} />);

    expect(await screen.findByRole("heading", { name: "TTLAB publication synchronization" })).toBeInTheDocument();
    expect(screen.getByText("Daily schedule: 0 2 * * * (America/La_Paz).")).toBeInTheDocument();
    expect(screen.getByText(/7\/21\/2026/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Request synchronization now" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Synchronization queued" })).toBeDisabled());
    expect(notify).toHaveBeenCalledWith("Synchronization request queued for the ingestion worker.", "success");
    const request = fetchMock.mock.calls.find(([input]) => String(input).includes("/api/admin/ingestion-sync/request"));
    expect(request?.[1]).toMatchObject({
      method: "POST",
      headers: expect.objectContaining({ Authorization: `Bearer ${"a".repeat(32)}` }),
    });
  });
});
